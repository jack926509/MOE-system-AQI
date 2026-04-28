"""Telegram Bot：8 個指令。

啟動：
    python -m system_b_air.bot
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import timedelta

from sqlalchemy import select
from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from core import load_settings
from core.db import Database
from core.notifier import TelegramNotifier
from core.time_utils import now_taipei
from system_b_air.alert import aqi_flag, aqi_flag_from_str, pollutant_short
from system_b_air.daily_report import send_daily_report
from system_b_air.formatting import (
    display_width,
    fmt_num,
    pad,
    sparkline,
    trend_arrow,
    truncate,
)
from system_b_air.models import AQIRecord, ForecastRecord
from system_b_air.regions import (
    REGION_COUNTIES,
    REGIONS,
    region_alias,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "👋 <b>環境部空品 Bot</b>　<i>8 區監看版</i>\n"
    "\n"
    "<b>📊 即時</b>\n"
    "  /now — 全台 8 區排行\n"
    "  /aqi &lt;區或站&gt; — 區排行 ／ 單站詳情\n"
    "  /trend &lt;站&gt; [hours] — 近 N 小時走勢（最多 168h）\n"
    "  /regions — 8 區所屬縣市\n"
    "\n"
    "<b>📅 預報 / 摘要</b>\n"
    "  /forecast &lt;區&gt; — 1–3 日預報\n"
    "  /report — 24h 空品日報\n"
    "\n"
    "<i>例：/aqi 中部　/trend 沙鹿 12　/forecast 北部</i>"
)


def _latest_records(db: Database) -> list[AQIRecord]:
    """單次 query：取最新 publish_time 的所有站點。"""
    with db.session() as session:
        subq = select(AQIRecord.publish_time).order_by(
            AQIRecord.publish_time.desc()
        ).limit(1).scalar_subquery()
        return list(
            session.execute(
                select(AQIRecord).where(AQIRecord.publish_time == subq)
            ).scalars()
        )


def _hint(*lines: str) -> str:
    """訊息底部小字提示。"""
    return "\n".join(f"<i>{line}</i>" for line in lines)


# ───── handlers ─────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    rows = await asyncio.to_thread(_latest_records, db)
    by_region: dict[str, list[AQIRecord]] = {r: [] for r in REGIONS}
    for r in rows:
        by_region.setdefault(r.region, []).append(r)

    # 緊湊表格：旗 區 均 站數
    table_lines: list[str] = [
        f"   {pad('區', 6)} {pad('均', 3, 'right')} {pad('站數', 4, 'right')}",
        "   " + "─" * 6 + " " + "─" * 3 + " " + "─" * 4,
    ]
    for region in REGIONS:
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        avg = (sum(aqis) / len(aqis)) if aqis else None
        flag, _ = aqi_flag(avg)
        avg_str = f"{int(avg):>3}" if avg is not None else "  —"
        table_lines.append(
            f"{flag} {pad(region, 6)} {avg_str} {len(group):>4}"
        )

    # 縣市列表分行顯示，避免一行擠到爆
    detail_blocks: list[str] = []
    for region in REGIONS:
        counties = "、".join(REGION_COUNTIES[region])
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        avg = (sum(aqis) / len(aqis)) if aqis else None
        flag, _ = aqi_flag(avg)
        detail_blocks.append(
            f"{flag} <b>{html.escape(region)}</b>\n"
            f"   {html.escape(counties)}"
        )

    msg = (
        "🗺️ <b>8 區與所屬縣市</b>\n\n"
        + "<pre>"
        + "\n".join(html.escape(t) for t in table_lines)
        + "</pre>\n\n"
        + "\n\n".join(detail_blocks)
    )
    await update.message.reply_html(msg)


async def cmd_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    rows = await asyncio.to_thread(_latest_records, db)
    if not rows:
        await update.message.reply_text(
            "尚無資料。請確認：\n"
            "1) 已設定 MOENV_API_KEY 並通過 verify_dataids.py\n"
            "2) scheduler.py 已啟動並至少跑過一次 ETL\n"
            "3) 可手動執行：python -m system_b_air.etl_realtime"
        )
        return
    by_region: dict[str, list[AQIRecord]] = {r: [] for r in REGIONS}
    for r in rows:
        by_region.setdefault(r.region, []).append(r)

    # 排序：均 AQI 由低到高（前面越好），無資料置最後
    region_stats: list[tuple[str, list[AQIRecord]]] = []
    for region in REGIONS:
        region_stats.append((region, by_region.get(region, [])))
    region_stats.sort(
        key=lambda kv: (
            1 if not [r for r in kv[1] if r.aqi is not None] else 0,
            (sum(r.aqi for r in kv[1] if r.aqi is not None)
             / max(1, len([r for r in kv[1] if r.aqi is not None]))),
        )
    )

    # 表頭：「   」對應 emoji 旗 (2 寬) + 1 空格
    table: list[str] = [
        f"   {pad('區', 6)} {pad('均', 3, 'right')} "
        f"{pad('高', 3, 'right')}  {pad('最差站', 10)} {pad('站', 2, 'right')}",
        "   " + "─" * 6 + " " + "─" * 3 + " " + "─" * 3 + "  "
            + "─" * 10 + " " + "─" * 2,
    ]
    for region, group in region_stats:
        aqis = [r.aqi for r in group if r.aqi is not None]
        n = len(group)
        if not aqis:
            table.append(
                f"⚪ {pad(region, 6)} {'—':>3} {'—':>3}  "
                f"{pad('無資料', 10)} {0:>2}"
            )
            continue
        avg = sum(aqis) / len(aqis)
        worst = max(
            (r for r in group if r.aqi is not None), key=lambda r: r.aqi or 0
        )
        flag, _ = aqi_flag(avg)
        worst_name = truncate(worst.site_name, 10)
        table.append(
            f"{flag} {pad(region, 6)} "
            f"{int(avg):>3} {int(worst.aqi):>3}  "
            f"{pad(worst_name, 10)} {n:>2}"
        )

    # 區級摘要
    summary_lines: list[str] = []
    bad_regions = [
        (region, max((r.aqi or 0) for r in g))
        for region, g in region_stats
        if any(r.aqi is not None and r.aqi >= 100 for r in g)
    ]
    if bad_regions:
        names = "、".join(html.escape(n) for n, _ in bad_regions)
        summary_lines.append(f"⚠️ 普通以上：{names}")
    else:
        summary_lines.append("✅ 全台空品良好")

    publish = max(r.publish_time for r in rows).strftime("%m-%d %H:%M")
    msg = (
        "🌫️ <b>全台 8 區即時空品</b>\n"
        + f"<i>{publish} ‧ {len(rows)} 站</i>\n\n"
        + "<pre>"
        + "\n".join(html.escape(t) for t in table)
        + "</pre>\n\n"
        + "\n".join(summary_lines)
        + "\n"
        + _hint(
            "🗺️ 看區內排行 → /aqi &lt;區&gt;",
            "📈 看單站走勢 → /trend &lt;站&gt;",
        )
    )
    await update.message.reply_html(msg)


async def cmd_aqi(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text(
            "用法：/aqi <區或測站>\n例如 /aqi 中部 或 /aqi 沙鹿"
        )
        return
    keyword = " ".join(ctx.args).strip()
    region = region_alias(keyword)
    rows = await asyncio.to_thread(_latest_records, db)

    if region:
        group = [r for r in rows if r.region == region]
        if not group:
            await update.message.reply_text(f"{region} 尚無資料")
            return
        group.sort(key=lambda r: -(r.aqi or 0))

        table: list[str] = [" # 站         AQI PM2.5 主"]
        table.append("── ───────── ─── ───── ─────")
        for i, r in enumerate(group, 1):
            flag, _ = aqi_flag(r.aqi)
            site = truncate(r.site_name, 9)
            aqi = fmt_num(r.aqi, ">3.0f")
            pm = fmt_num(r.pm25, ">5.1f")
            poll = truncate(pollutant_short(r.pollutant), 5)
            table.append(
                f"{i:>2}{flag}{pad(site, 9)} {aqi} {pm} {poll}"
            )

        # 區內統計
        aqis = [r.aqi for r in group if r.aqi is not None]
        avg = sum(aqis) / len(aqis) if aqis else None
        avg_flag, avg_label = aqi_flag(avg) if avg is not None else ("⚪", "—")
        bad_n = sum(1 for r in group if r.aqi is not None and r.aqi >= 100)

        publish = max(r.publish_time for r in group).strftime("%m-%d %H:%M")
        header_summary = (
            f"{avg_flag} 區均 {int(avg) if avg is not None else '—'}"
            f"（{avg_label}）"
            + (f"　⚠️ 普通以上 {bad_n}/{len(group)} 站" if bad_n else "")
        )
        msg = (
            f"🗺️ <b>{html.escape(region)} 即時站排行</b>\n"
            f"<i>{publish} ‧ {len(group)} 站</i>\n\n"
            + header_summary + "\n\n"
            + "<pre>"
            + "\n".join(html.escape(t) for t in table)
            + "</pre>\n"
            + _hint("看單站詳情 → /aqi &lt;站名&gt;")
        )
        await update.message.reply_html(msg)
        return

    # 否則視為測站名（精確優先，部分匹配次之）
    target = [r for r in rows if r.site_name == keyword]
    if not target:
        target = [r for r in rows if keyword in r.site_name]
    if not target:
        await update.message.reply_text(
            f"找不到測站「{keyword}」\n試試 /now 或 /regions"
        )
        return
    r = target[0]
    flag, label = aqi_flag(r.aqi)

    body = [
        ("AQI",   fmt_num(r.aqi, ".0f"),  ""),
        ("PM2.5", fmt_num(r.pm25, ".1f"), "μg/m³"),
        ("PM10",  fmt_num(r.pm10, ".1f"), "μg/m³"),
        ("O₃",    fmt_num(r.o3, ".1f"),   "ppb"),
        ("NO₂",   fmt_num(r.no2, ".3f"),  "ppm"),
        ("SO₂",   fmt_num(r.so2, ".3f"),  "ppm"),
        ("CO",    fmt_num(r.co, ".2f"),   "ppm"),
    ]
    label_w = max(display_width(k) for k, _, _ in body)
    val_w = max(display_width(v) for _, v, _ in body)
    table_lines = [
        f"{pad(k, label_w)}  {pad(v, val_w, 'right')} {u}".rstrip()
        for k, v, u in body
    ]

    msg = (
        f"{flag} <b>{html.escape(r.site_name)}</b>"
        f"　<i>{html.escape(r.region)}</i>\n"
        f"<b>{label}</b>　主污染：{html.escape(pollutant_short(r.pollutant))}\n\n"
        + "<pre>"
        + "\n".join(html.escape(t) for t in table_lines)
        + "</pre>\n"
        + f"🕐 {r.publish_time.strftime('%Y-%m-%d %H:%M')}\n"
        + _hint(
            f"📈 走勢 → /trend {html.escape(r.site_name)}",
            f"🗺️ 同區 → /aqi {html.escape(r.region)}",
        )
    )
    await update.message.reply_html(msg)


def _parse_hours(args: list[str], default: int = 24, max_hours: int = 168) -> tuple[str, int]:
    """從 args 取「測站名 + 可選時數」。最多 168h。"""
    if not args:
        return "", default
    hours = default
    site_args = list(args)
    if len(args) >= 2:
        last = args[-1]
        try:
            h = int(last)
            if 1 <= h <= max_hours:
                hours = h
                site_args = args[:-1]
        except ValueError:
            pass
    return " ".join(site_args).strip(), hours


async def cmd_trend(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text(
            "用法：/trend <測站> [hours]\n例如 /trend 沙鹿 12"
        )
        return
    keyword, hours = _parse_hours(ctx.args)
    if not keyword:
        await update.message.reply_text("請提供測站名稱")
        return
    cutoff = now_taipei() - timedelta(hours=hours)

    def _query() -> list[AQIRecord]:
        with db.session() as session:
            return list(session.execute(
                select(AQIRecord)
                .where(
                    AQIRecord.site_name == keyword,
                    AQIRecord.publish_time >= cutoff,
                )
                .order_by(AQIRecord.publish_time.asc())
            ).scalars())

    rows = await asyncio.to_thread(_query)
    if not rows:
        await update.message.reply_text(
            f"找不到「{keyword}」近 {hours}h 趨勢資料"
        )
        return

    aqi_series = [r.aqi for r in rows]
    spark = sparkline(aqi_series)
    arrow, delta = trend_arrow(aqi_series)
    nums = [v for v in aqi_series if v is not None]
    avg = sum(nums) / len(nums) if nums else None
    peak_row = (
        max((r for r in rows if r.aqi is not None), key=lambda r: r.aqi or 0)
        if nums else None
    )
    lo = min(nums) if nums else None
    hi = max(nums) if nums else None

    region = rows[0].region

    # 表格只顯示最後 24 列避免訊息過長；跨日才秀日期
    display_rows = rows[-24:]
    multi_day = len({r.publish_time.date() for r in display_rows}) > 1
    truncated = len(rows) - len(display_rows)

    table: list[str] = []
    if multi_day:
        table.append("時間       AQI  PM2.5")
        table.append("────────── ───  ─────")
    else:
        table.append("時 AQI  PM2.5")
        table.append("── ───  ─────")
    for r in display_rows:
        flag, _ = aqi_flag(r.aqi)
        ts = (
            r.publish_time.strftime("%m-%d %H:%M")
            if multi_day
            else r.publish_time.strftime("%H:%M")
        )
        marker = " ←高" if peak_row is not None and r is peak_row else ""
        ts_field = ts if multi_day else ts[:2]
        table.append(
            f"{ts_field} {flag} {fmt_num(r.aqi, '>3.0f')}  "
            f"{fmt_num(r.pm25, '>5.1f')}{marker}"
        )

    spark_line = ""
    if spark:
        scale = (
            f"{int(lo):>3}─{int(hi):<3}" if (lo is not None and hi is not None)
            else ""
        )
        spark_line = f"{scale} {spark}".strip()

    summary_parts = []
    if avg is not None:
        summary_parts.append(f"均 {avg:.0f}")
    if peak_row is not None and peak_row.aqi is not None:
        summary_parts.append(
            f"高 {peak_row.aqi:.0f}（{peak_row.publish_time.strftime('%m-%d %H:%M')}）"
        )
    if arrow:
        summary_parts.append(
            f"變化 {arrow} {f'{delta:+.0f}' if delta is not None else ''}"
        )
    summary = "　│　".join(summary_parts)

    msg = (
        f"📈 <b>{html.escape(keyword)}</b>　"
        f"<i>{html.escape(region)}　近 {hours}h</i>\n\n"
        + (f"<pre>{html.escape(spark_line)}</pre>\n" if spark_line else "")
        + (f"{summary}\n\n" if summary else "")
        + "<pre>"
        + "\n".join(html.escape(t) for t in table)
        + "</pre>\n"
        + (f"<i>（僅顯示最近 {len(display_rows)} 筆，省略 {truncated} 筆較舊資料）</i>\n"
           if truncated > 0 else "")
        + _hint(f"看單站詳情 → /aqi {html.escape(keyword)}")
    )
    await update.message.reply_html(msg)


async def cmd_forecast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text(
            "用法：/forecast <區>\n例如 /forecast 北部"
        )
        return
    region = region_alias(" ".join(ctx.args).strip())
    if not region:
        await update.message.reply_text(
            "找不到該區，可用：" + "、".join(REGIONS)
        )
        return

    def _query() -> list[ForecastRecord]:
        with db.session() as session:
            return list(session.execute(
                select(ForecastRecord)
                .where(ForecastRecord.region == region)
                .order_by(ForecastRecord.publish_time.desc())
                .limit(3)
            ).scalars())

    rows = await asyncio.to_thread(_query)
    if not rows:
        await update.message.reply_text(f"{region} 尚無預報資料")
        return

    # 依日期升冪重排（DB 是 publish desc）
    rows = sorted(rows, key=lambda r: r.forecast_date)

    blocks: list[str] = []
    for r in rows:
        flag, _ = aqi_flag_from_str(r.aqi)
        aqi_text = r.aqi or "—"
        head = (
            f"{flag} <b>{html.escape(r.forecast_date)}</b>　"
            f"AQI {html.escape(aqi_text)}"
        )
        if r.aqi_status:
            head += f"　{html.escape(r.aqi_status)}"
        block = [head]
        polls = []
        if r.major_pollutant:
            polls.append(f"主 {html.escape(pollutant_short(r.major_pollutant))}")
        if r.minor_pollutant:
            polls.append(f"次 {html.escape(pollutant_short(r.minor_pollutant))}")
        if polls:
            block.append("　" + "　".join(polls))
        if r.content:
            block.append(f"　📝 {html.escape(r.content)}")
        blocks.append("\n".join(block))

    publish_at = max(r.publish_time for r in rows).strftime("%m-%d %H:%M")
    msg = (
        f"🌤️ <b>{html.escape(region)} 空品預報</b>\n"
        f"<i>發布 {publish_at}</i>\n"
        f"\n"
        + "\n────────────\n".join(blocks)
    )
    await update.message.reply_html(msg)


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    notifier: TelegramNotifier = ctx.application.bot_data["notifier"]
    chat_id = str(update.effective_chat.id)
    ok = await asyncio.to_thread(send_daily_report, db, notifier, chat_id)
    if not ok:
        await update.message.reply_text("日報傳送失敗，請稍後再試")


async def _on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Handler error", exc_info=ctx.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("系統忙碌，請稍後再試。")
        except Exception:
            pass


BOT_COMMANDS: list[BotCommand] = [
    BotCommand("now", "全台 8 區即時總覽"),
    BotCommand("aqi", "區排行或單站詳情：/aqi <區或站>"),
    BotCommand("trend", "近 N 小時走勢：/trend <站> [hours]"),
    BotCommand("forecast", "區域 1–3 日預報：/forecast <區>"),
    BotCommand("regions", "8 區與所屬縣市"),
    BotCommand("report", "立即產 24h 空品日報"),
    BotCommand("help", "顯示說明"),
]


async def _post_init(app: Application) -> None:
    """Bot 啟動後向 Telegram 註冊命令清單，輸入 / 時會浮出選單。"""
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
        logger.info("已向 Telegram 註冊 %d 個命令", len(BOT_COMMANDS))
    except Exception as exc:  # noqa: BLE001
        logger.warning("註冊命令清單失敗：%s", exc)


def build_app() -> Application:
    settings = load_settings()
    if not settings.telegram.bot_token:
        raise SystemExit("settings.telegram.bot_token 未設定，無法啟動 Bot")
    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    notifier = TelegramNotifier(settings.telegram.bot_token)

    app = (
        Application.builder()
        .token(settings.telegram.bot_token)
        .post_init(_post_init)
        .build()
    )
    app.bot_data["db"] = db
    app.bot_data["notifier"] = notifier
    app.bot_data["settings"] = settings

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("regions", cmd_regions))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("aqi", cmd_aqi))
    app.add_handler(CommandHandler("trend", cmd_trend))
    app.add_handler(CommandHandler("forecast", cmd_forecast))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_error_handler(_on_error)
    return app


def main() -> None:
    app = build_app()
    logger.info("Bot 啟動中…（Ctrl+C 離開）")
    app.run_polling()


if __name__ == "__main__":
    main()
