"""APScheduler 排程：AQI ETL/告警、預報、日報三個 jobs。獨立進程執行。"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core import load_settings
from core.db import Database
from core.notifier import TelegramNotifier
from system_b_air import alert as alert_mod
from system_b_air import daily_report as daily_mod
from system_b_air import etl_forecast as forecast_mod
from system_b_air import etl_realtime as realtime_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _air_db() -> Database:
    s = load_settings()
    return Database(s.databases.get("air_quality", "data/air_quality.db"))


def job_aqi_realtime() -> None:
    realtime_mod.run_etl()
    s = load_settings()
    notifier = (
        TelegramNotifier(s.telegram.bot_token)
        if s.telegram.bot_token else None
    )
    chat_id = s.telegram.chat_ids.get("alert")
    alert_mod.run_alerts(
        _air_db(), notifier,
        s.air_quality_alerts.station,
        s.air_quality_alerts.region,
        chat_id=chat_id,
    )


def job_forecast() -> None:
    forecast_mod.run_etl()


def job_daily_report() -> None:
    s = load_settings()
    if not s.telegram.bot_token:
        logger.warning("daily_report: 無 bot_token，僅輸出至 stdout")
        print(daily_mod.build_daily_report(_air_db()))
        return
    notifier = TelegramNotifier(s.telegram.bot_token)
    daily_mod.send_daily_report(
        _air_db(), notifier, chat_id=s.telegram.chat_ids.get("daily")
    )


def main() -> None:
    settings = load_settings()
    sched = BlockingScheduler(timezone="Asia/Taipei")

    sched.add_job(job_aqi_realtime, CronTrigger(minute=5), id="aqi_etl_alert")
    sched.add_job(job_forecast, CronTrigger(minute="*/30"), id="forecast_etl")
    sched.add_job(
        job_daily_report,
        CronTrigger(
            hour=settings.daily_report.hour,
            minute=settings.daily_report.minute,
            timezone=settings.daily_report.timezone,
        ),
        id="daily_report",
    )

    if settings.telegram.bot_token:
        try:
            n = TelegramNotifier(settings.telegram.bot_token)
            me = n.get_me()
            logger.info("Telegram getMe ok: %s", me.get("result", {}).get("username"))
            admin = settings.telegram.chat_ids.get("admin")
            if admin:
                n.send_message(
                    f"✓ AQI 排程 scheduler 已啟動 @ {datetime.now():%Y-%m-%d %H:%M}",
                    chat_id=admin,
                )
        except Exception as e:
            logger.error("Telegram 啟動驗證失敗：%s", e)

    logger.info("Scheduler 啟動，按 Ctrl+C 結束")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler 結束")


if __name__ == "__main__":
    main()
