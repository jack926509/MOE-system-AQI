"""測站資料新鮮度檢查：watchlist 站台連續 N 小時無資料 → admin 通報。

去重以 AlertLog (scope='freshness', target=site_name, pollutant='stale', publish_time=最後資料時間) 進行。
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.db import Database
from core.notifier import TelegramNotifier
from core.time_utils import now_taipei
from system_b_air.models import AlertLog, AQIRecord

logger = logging.getLogger(__name__)


def find_stale_sites(
    db: Database, watchlist: list[str], stale_hours: int = 3,
) -> list[tuple[str, datetime | None]]:
    """回傳 (site_name, last_publish_time | None)；若 last_publish < now - stale_hours 即視為失聯。"""
    if not watchlist:
        return []
    cutoff = now_taipei() - timedelta(hours=stale_hours)
    with db.session() as session:
        rows = session.execute(
            select(
                AQIRecord.site_name,
                func.max(AQIRecord.publish_time),
            )
            .where(AQIRecord.site_name.in_(watchlist))
            .group_by(AQIRecord.site_name)
        ).all()
    last_pub: dict[str, datetime] = {sn: mp for sn, mp in rows}
    stale: list[tuple[str, datetime | None]] = []
    for site in watchlist:
        mp = last_pub.get(site)
        if mp is None or mp < cutoff:
            stale.append((site, mp))
    return stale


def _dedup_and_persist(
    db: Database, items: list[tuple[str, datetime | None]],
) -> list[tuple[str, datetime | None]]:
    """同一 (site, last_pub) 已通報過則跳過。"""
    if not items:
        return []
    sentinel = datetime(1970, 1, 1)
    new_items: list[tuple[str, datetime | None]] = []
    rows: list[dict] = []
    with db.session() as session:
        keys = [(s, p or sentinel) for s, p in items]
        existing = session.execute(
            select(AlertLog.target, AlertLog.publish_time).where(
                AlertLog.scope == "freshness",
                AlertLog.target.in_({k[0] for k in keys}),
                AlertLog.publish_time.in_({k[1] for k in keys}),
            )
        ).all()
        existing_set = {(t, p) for t, p in existing}
        for site, pub in items:
            key = (site, pub or sentinel)
            if key in existing_set:
                continue
            new_items.append((site, pub))
            rows.append(
                dict(
                    scope="freshness",
                    target=site,
                    pollutant="stale",
                    value=None,
                    threshold=None,
                    publish_time=key[1],
                )
            )
        if rows:
            stmt = sqlite_insert(AlertLog).values(rows).on_conflict_do_nothing(
                index_elements=["scope", "target", "pollutant", "publish_time"]
            )
            session.execute(stmt)
            session.commit()
    return new_items


def run_freshness(
    db: Database,
    notifier: TelegramNotifier | None,
    watchlist: list[str],
    admin_chat_id: str | None,
    stale_hours: int = 3,
) -> int:
    """掃描 watchlist，連續 stale_hours 無新資料則發 admin。"""
    if not watchlist:
        return 0
    stale = find_stale_sites(db, watchlist, stale_hours=stale_hours)
    if not stale:
        return 0
    new_items = _dedup_and_persist(db, stale)
    if not new_items:
        logger.info("Freshness: %d stale sites already notified", len(stale))
        return 0
    if notifier and admin_chat_id:
        lines = [f"📡 <b>測站資料失聯</b>　<i>≥ {stale_hours}h 無新值</i>", ""]
        for site, last_pub in new_items:
            ts = last_pub.strftime("%Y-%m-%d %H:%M") if last_pub else "—（從未觀測）"
            lines.append(f"⚠ {html.escape(site)}　最後 {ts}")
        notifier.send_message("\n".join(lines), chat_id=admin_chat_id)
    logger.info("Freshness: %d sites stale, %d newly notified", len(stale), len(new_items))
    return len(new_items)
