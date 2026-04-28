"""Telegram Bot：8 個指令。

啟動：
    python -m system_b_air.bot
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from core import load_settings
from core.db import Database
from core.notifier import TelegramNotifier
from system_b_air.alert import aqi_flag
from system_b_air.daily_report import send_daily_report
from system_b_air.models import AQIRecord, ForecastRecord
from system_b_air.regions import (
    REGION_COUNTIES,
    REGIONS,
    region_alias,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "<b>環境部空品 Bot — 8 區監看版</b>\n\n"
    "/regions — 8 區與所屬縣市\n"
    "/now — 8 區即時總覽\n"
    "/aqi &lt;區 或 測站&gt; — 區或單站詳情\n"
    "/trend &lt;測站&gt; [hours] — 該站近 N 小時趨勢（預設 24）\n"
    "/forecast &lt;區&gt; — 該區明日預報\n"
    "/report — 立刻產 24h 日報\n"
    "/help — 顯示本說明"
)

# 顯示輔助：None 才以 — 取代，0 仍應顯示
def _fmt(value, spec: str = "") -> str:
    if value is None:
        return "—"
    if spec:
        return format(value, spec)
    return str(value)


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
    lines = ["<b>8 區與所屬縣市</b>", ""]
    for region in REGIONS:
        counties = "、".join(REGION_COUNTIES[region])
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        avg = (sum(aqis) / len(aqis)) if aqis else None
        flag, _ = aqi_flag(avg)
        avg_str = f"{avg:.0f}" if avg is not None else "—"
        lines.append(f"{flag} <b>{region}</b>（均 {avg_str}）：{counties}")
    await update.message.reply_html("\n".join(lines))


async def cmd_now(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    rows = await asyncio.to_thread(_latest_records, db)
    if not rows:
        await update.message.reply_text("尚無資料，請等下一輪 ETL")
        return
    by_region: dict[str, list[AQIRecord]] = {r: [] for r in REGIONS}
    for r in rows:
        by_region.setdefault(r.region, []).append(r)
    lines = ["<b>8 區即時總覽</b>", ""]
    for region in REGIONS:
        group = by_region.get(region, [])
        aqis = [r.aqi for r in group if r.aqi is not None]
        total = len(REGION_COUNTIES.get(region, ()))
        if not aqis:
            lines.append(f"⚪ <b>{region}</b>　0/{total} 站有資料")
            continue
        avg = sum(aqis) / len(aqis)
        worst = max((r for r in group if r.aqi is not None), key=lambda r: r.aqi or 0)
        flag, _ = aqi_flag(avg)
        lines.append(
            f"{flag} <b>{region}</b>　均 {avg:.0f}　"
            f"最高 {worst.aqi:.0f}（{html.escape(worst.site_name)}）"
        )
    publish = max(r.publish_time for r in rows).strftime("%m-%d %H:%M")
    lines.append("")
    lines.append(f"資料時間：{publish}")
    await update.message.reply_html("\n".join(lines))


async def cmd_aqi(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text("用法：/aqi <區或測站>，例如 /aqi 中部 或 /aqi 沙鹿")
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
        lines = [f"<b>{region} 即時測站</b>", ""]
        for r in group:
            flag, _ = aqi_flag(r.aqi)
            aqi = _fmt(r.aqi, ".0f")
            pm25 = _fmt(r.pm25, ".1f")
            poll = r.pollutant or "-"
            lines.append(
                f"{flag} <b>{html.escape(r.site_name)}</b>　"
                f"AQI {aqi}　PM2.5 {pm25}　主污染 {html.escape(poll)}"
            )
        await update.message.reply_html("\n".join(lines))
        return

    # 否則視為測站名（精確優先，部分匹配次之）
    target = [r for r in rows if r.site_name == keyword]
    if not target:
        target = [r for r in rows if keyword in r.site_name]
    if not target:
        await update.message.reply_text(f"找不到測站「{keyword}」，請試 /now 或 /regions")
        return
    r = target[0]
    flag, label = aqi_flag(r.aqi)
    lines = [
        f"{flag} <b>[{r.region}][{html.escape(r.site_name)}]</b>　{label}",
        "",
        f"AQI　 {_fmt(r.aqi, '.0f')}",
        f"PM2.5 {_fmt(r.pm25, '.1f')} μg/m³",
        f"PM10　{_fmt(r.pm10, '.1f')} μg/m³",
        f"O3　 {_fmt(r.o3, '.1f')} ppb",
        f"SO2　{_fmt(r.so2, '.3f')} ppm",
        f"NO2　{_fmt(r.no2, '.3f')} ppm",
        f"CO　 {_fmt(r.co, '.2f')} ppm",
        f"主污染 {html.escape(r.pollutant or '-')}",
        "",
        f"時間 {r.publish_time.strftime('%Y-%m-%d %H:%M')}",
    ]
    await update.message.reply_html("\n".join(lines))


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
            "用法：/trend <測站> [hours]，例如 /trend 沙鹿 12"
        )
        return
    keyword, hours = _parse_hours(ctx.args)
    if not keyword:
        await update.message.reply_text("請提供測站名稱")
        return
    cutoff = datetime.now() - timedelta(hours=hours)

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
        await update.message.reply_text(f"找不到「{keyword}」近 {hours}h 趨勢資料")
        return
    lines = [
        f"<b>[{rows[0].region}][{html.escape(keyword)}] 近 {hours}h 趨勢</b>",
        "",
    ]
    for r in rows:
        flag, _ = aqi_flag(r.aqi)
        ts = r.publish_time.strftime("%m-%d %H:%M")
        aqi = _fmt(r.aqi, ".0f")
        pm25 = _fmt(r.pm25, ".1f")
        lines.append(f"{flag} {ts}　AQI {aqi}　PM2.5 {pm25}")
    await update.message.reply_html("\n".join(lines))


async def cmd_forecast(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text("用法：/forecast <區>，例如 /forecast 北部")
        return
    region = region_alias(" ".join(ctx.args).strip())
    if not region:
        await update.message.reply_text("找不到該區，可用：" + "、".join(REGIONS))
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
    lines = [f"<b>{region} 預報</b>", ""]
    for r in rows:
        lines.append(
            f"📅 <b>{html.escape(r.forecast_date)}</b>　"
            f"AQI {html.escape(r.aqi or '—')}（{html.escape(r.aqi_status or '-')}）"
        )
        if r.major_pollutant:
            lines.append(f"  主：{html.escape(r.major_pollutant)}")
        if r.minor_pollutant:
            lines.append(f"  次：{html.escape(r.minor_pollutant)}")
        if r.content:
            lines.append(f"  {html.escape(r.content)}")
        lines.append("")
    await update.message.reply_html("\n".join(lines))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    notifier: TelegramNotifier = ctx.application.bot_data["notifier"]
    chat_id = str(update.effective_chat.id)
    # 同步 send 包進 thread，避免阻塞 PTB event loop
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


def build_app() -> Application:
    settings = load_settings()
    if not settings.telegram.bot_token:
        raise SystemExit("settings.telegram.bot_token 未設定，無法啟動 Bot")
    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    notifier = TelegramNotifier(settings.telegram.bot_token)

    app = Application.builder().token(settings.telegram.bot_token).build()
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
