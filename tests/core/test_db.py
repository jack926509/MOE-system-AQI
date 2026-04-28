import tempfile
from pathlib import Path

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base, Database


class Sample(Base):
    __tablename__ = "samples_test_db"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))


def test_database_create_and_session():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "x.db")
        db = Database(path)
        db.create_all()
        with db.session() as s:
            s.add(Sample(name="ok"))
            s.commit()
        with db.session() as s:
            row = s.query(Sample).first()
            assert row.name == "ok"
