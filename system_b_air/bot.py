"""Telegram Bot：8 個指令。

啟動：
    python -m system_b_air.bot
"""
from __future__ import annotations

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
    "/trend &lt;測站&gt; — 該站近 24h 趨勢\n"
    "/forecast &lt;區&gt; — 該區明日預報\n"
    "/report — 立刻產 24h 日報\n"
    "/help — 顯示本說明"
)


def _latest_records(db: Database) -> list[AQIRecord]:
    with db.session() as session:
        latest = session.execute(
            select(AQIRecord.publish_time).order_by(AQIRecord.publish_time.desc()).limit(1)
        ).scalar_one_or_none()
        if latest is None:
            return []
        return list(
            session.execute(
                select(AQIRecord).where(AQIRecord.publish_time == latest)
            ).scalars()
        )


# ───── handlers ─────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


async def cmd_regions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    rows = _latest_records(db)
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
    rows = _latest_records(db)
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
        if not aqis:
            lines.append(f"⚪ <b>{region}</b>　0/{len(REGION_COUNTIES[region])} 站有資料")
            continue
        avg = sum(aqis) / len(aqis)
        worst = max((r for r in group if r.aqi is not None), key=lambda r: r.aqi or 0)
        flag, _ = aqi_flag(avg)
        lines.append(
            f"{flag} <b>{region}</b>　均 {avg:.0f}　"
            f"最高 {worst.aqi:.0f}（{worst.site_name}）"
        )
    publish = rows[0].publish_time.strftime("%m-%d %H:%M")
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
    rows = _latest_records(db)
    if region:
        group = [r for r in rows if r.region == region]
        if not group:
            await update.message.reply_text(f"{region} 尚無資料")
            return
        group.sort(key=lambda r: -(r.aqi or 0))
        lines = [f"<b>{region} 即時測站</b>", ""]
        for r in group:
            flag, _ = aqi_flag(r.aqi)
            aqi = f"{r.aqi:.0f}" if r.aqi is not None else "—"
            pm25 = f"{r.pm25:.1f}" if r.pm25 is not None else "—"
            poll = r.pollutant or "-"
            lines.append(
                f"{flag} <b>{r.site_name}</b>　AQI {aqi}　PM2.5 {pm25}　主污染 {poll}"
            )
        await update.message.reply_html("\n".join(lines))
        return

    # 否則視為測站名（精確或部分匹配）
    target = [r for r in rows if r.site_name == keyword]
    if not target:
        target = [r for r in rows if keyword in r.site_name]
    if not target:
        await update.message.reply_text(f"找不到測站「{keyword}」，請試 /now 或 /regions")
        return
    r = target[0]
    flag, label = aqi_flag(r.aqi)
    lines = [
        f"{flag} <b>[{r.region}][{r.site_name}]</b>　{label}",
        "",
        f"AQI　 {r.aqi or '—'}",
        f"PM2.5 {r.pm25 or '—'} μg/m³",
        f"PM10　{r.pm10 or '—'} μg/m³",
        f"O3　 {r.o3 or '—'} ppb",
        f"SO2　{r.so2 or '—'} ppb",
        f"NO2　{r.no2 or '—'} ppb",
        f"CO　 {r.co or '—'} ppm",
        f"主污染 {r.pollutant or '-'}",
        "",
        f"時間 {r.publish_time.strftime('%Y-%m-%d %H:%M')}",
    ]
    await update.message.reply_html("\n".join(lines))


async def cmd_trend(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    if not ctx.args:
        await update.message.reply_text("用法：/trend <測站>，例如 /trend 沙鹿")
        return
    keyword = " ".join(ctx.args).strip()
    cutoff = datetime.now() - timedelta(hours=24)
    with db.session() as session:
        rows = list(session.execute(
            select(AQIRecord)
            .where(AQIRecord.site_name == keyword, AQIRecord.publish_time >= cutoff)
            .order_by(AQIRecord.publish_time.desc())
            .limit(12)
        ).scalars())
    if not rows:
        await update.message.reply_text(f"找不到「{keyword}」的趨勢資料")
        return
    rows.reverse()
    lines = [f"<b>[{rows[0].region}][{keyword}] 近 24h 趨勢</b>", ""]
    for r in rows:
        flag, _ = aqi_flag(r.aqi)
        ts = r.publish_time.strftime("%m-%d %H:%M")
        aqi = f"{r.aqi:.0f}" if r.aqi is not None else "—"
        pm25 = f"{r.pm25:.1f}" if r.pm25 is not None else "—"
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
    with db.session() as session:
        rows = list(session.execute(
            select(ForecastRecord)
            .where(ForecastRecord.region == region)
            .order_by(ForecastRecord.publish_time.desc())
            .limit(3)
        ).scalars())
    if not rows:
        await update.message.reply_text(f"{region} 尚無預報資料")
        return
    lines = [f"<b>{region} 預報</b>", ""]
    for r in rows:
        lines.append(
            f"📅 <b>{r.forecast_date}</b>　AQI {r.aqi or '—'}（{r.aqi_status or '-'}）"
        )
        if r.major_pollutant:
            lines.append(f"  主：{r.major_pollutant}")
        if r.minor_pollutant:
            lines.append(f"  次：{r.minor_pollutant}")
        if r.content:
            lines.append(f"  {r.content}")
        lines.append("")
    await update.message.reply_html("\n".join(lines))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = ctx.application.bot_data["db"]
    notifier: TelegramNotifier = ctx.application.bot_data["notifier"]
    chat_id = str(update.effective_chat.id)
    send_daily_report(db, notifier, chat_id=chat_id)


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
    return app


def main() -> None:
    app = build_app()
    logger.info("Bot 啟動中…（Ctrl+C 離開）")
    app.run_polling()


if __name__ == "__main__":
    main()
