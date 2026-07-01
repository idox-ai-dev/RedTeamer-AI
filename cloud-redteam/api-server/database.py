from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./redteam.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from models_db import Client, Scenario, AttackSession, Event, Evaluation  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_add_columns()


def _migrate_add_columns():
    """Add/remove columns on existing tables (SQLite only)."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        from sqlalchemy import text
        events_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(events)"))}
        for col, ddl in [
            ("tool_result",   "ALTER TABLE events ADD COLUMN tool_result TEXT"),
            ("attack_run_id", "ALTER TABLE events ADD COLUMN attack_run_id TEXT"),
        ]:
            if col not in events_cols:
                conn.execute(text(ddl))

        scenarios_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(scenarios)"))}
        if "risk_type" in scenarios_cols:
            conn.execute(text("ALTER TABLE scenarios DROP COLUMN risk_type"))
        for col, ddl in [
            ("type",            "ALTER TABLE scenarios ADD COLUMN type TEXT NOT NULL DEFAULT 'agent_attack'"),
            ("evaluation_json", "ALTER TABLE scenarios ADD COLUMN evaluation_json TEXT NOT NULL DEFAULT '{}'"),
        ]:
            if col not in scenarios_cols:
                conn.execute(text(ddl))

        conn.commit()
