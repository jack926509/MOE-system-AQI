"""SQLAlchemy 工廠：每個系統各自一支 SQLite，避免寫鎖衝突。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """三系統共用的 ORM Base。各系統 models 從這裡繼承。"""


class Database:
    """以 db_path 為 key 的 SQLite 工廠。"""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
            connect_args={"check_same_thread": False},
        )
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
