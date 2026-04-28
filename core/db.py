"""SQLAlchemy 工廠：每個系統各自一支 SQLite，避免寫鎖衝突。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """三系統共用的 ORM Base。各系統 models 從這裡繼承。"""


def _apply_sqlite_pragmas(dbapi_conn, _conn_record) -> None:
    """每次新連線啟用 WAL + busy_timeout，提升 bot/scheduler 並發容忍度。"""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
    finally:
        cur.close()


class Database:
    """以 db_path 為 key 的 SQLite 工廠。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        event.listen(self.engine, "connect", _apply_sqlite_pragmas)
        self._sessionmaker = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=Session
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        Base.metadata.drop_all(self.engine)

    def session(self) -> Session:
        return self._sessionmaker()

    def __repr__(self) -> str:
        size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return f"<Database path={self.db_path} size={size}B>"
