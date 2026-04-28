"""APScheduler 排程：AQI ETL/告警、預報、日報三個 jobs。獨立進程執行。"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from core import load_settings, now_taipei
from core.config import Settings
from core.db import Database
from core.notifier import TelegramNotifier
from system_b_air import alert as alert_mod
from system_b_air import daily_report as daily_mod
from system_b_air import etl_forecast as forecast_mod
from system_b_air import etl_realtime as realtime_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _safe(job_name: str):
    """裝飾器：捕捉 job 例外避免 scheduler 崩潰。"""
    def deco(fn):
        def wrapper(*args, **kwargs):
            try:
                fn(*args, **kwargs)
            except Exception:
                logger.exception("job %s failed", job_name)
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco


def make_jobs(settings: Settings, db: Database, notifier: TelegramNotifier | None):
    alert_chat = settings.telegram.chat_ids.get("alert")
    daily_chat = settings.telegram.chat_ids.get("daily")

    @_safe("aqi_etl_alert")
    def job_aqi_realtime() -> None:
        realtime_mod.run_etl()
        alert_mod.run_alerts(
            db,
            notifier,
            settings.air_quality_alerts.station,
            settings.air_quality_alerts.region,
            chat_id=alert_chat,
        )

    @_safe("forecast_etl")
    def job_forecast() -> None:
        forecast_mod.run_etl()

    @_safe("daily_report")
    def job_daily_report() -> None:
        if notifier is None:
            logger.warning("daily_report: 無 notifier，僅輸出至 stdout")
            print(daily_mod.build_daily_report(db))
            return
        daily_mod.send_daily_report(db, notifier, chat_id=daily_chat)

    return job_aqi_realtime, job_forecast, job_daily_report


def main() -> None:
    settings = load_settings()
    if not settings.moenv.api_key:
        raise SystemExit(
            "MoEnv API key 未設定（請填 .env MOENV_API_KEY 或 settings.moenv.api_key），無法啟動 scheduler"
        )

    db = Database(settings.databases.get("air_quality", "data/air_quality.db"))
    db.create_all()

    notifier: TelegramNotifier | None = None
    if settings.telegram.bot_token:
        notifier = TelegramNotifier(settings.telegram.bot_token)
        try:
            me = notifier.get_me()
            logger.info("Telegram getMe ok: %s", me.get("result", {}).get("username"))
            admin = settings.telegram.chat_ids.get("admin")
            if admin:
                notifier.send_message(
                    f"✓ AQI 排程 scheduler 已啟動 @ {now_taipei():%Y-%m-%d %H:%M}",
                    chat_id=admin,
                )
        except Exception as e:
            logger.error("Telegram 啟動驗證失敗：%s", e)
    else:
        logger.warning("未設定 telegram.bot_token，告警與日報只會寫入 DB / log")

    job_aqi, job_fc, job_daily = make_jobs(settings, db, notifier)

    # 啟動時先跑一次 ETL，避免新部署到下一個 :15 之間整段沒資料
    logger.info("初始化：立即執行一次 AQI / 預報 ETL")
    job_aqi()
    job_fc()

    tz = settings.daily_report.timezone
    sched = BlockingScheduler(timezone=tz)

    # AQI 即時 + 告警：每整點 :15（讓官方完成 publish 後再抓）
    sched.add_job(
        job_aqi, CronTrigger(minute=15, timezone=tz), id="aqi_etl_alert"
    )

    # 預報：對齊官方每日 3 次正式發布時點（10:30 / 16:30 / 22:00）
    sched.add_job(
        job_fc,
        OrTrigger(
            [
                CronTrigger(hour=10, minute=30, timezone=tz),
                CronTrigger(hour=16, minute=30, timezone=tz),
                CronTrigger(hour=22, minute=0, timezone=tz),
            ]
        ),
        id="forecast_etl",
    )

    # 8 區日報：每日 08:00
    sched.add_job(
        job_daily,
        CronTrigger(
            hour=settings.daily_report.hour,
            minute=settings.daily_report.minute,
            timezone=tz,
        ),
        id="daily_report",
    )

    logger.info("Scheduler 啟動，按 Ctrl+C 結束")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler 結束")
    finally:
        if notifier is not None:
            notifier.close()


if __name__ == "__main__":
    main()
