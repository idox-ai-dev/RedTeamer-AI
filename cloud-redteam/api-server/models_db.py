from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Client(Base):
    __tablename__ = "clients"

    id:           Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name:         Mapped[str] = mapped_column(String, unique=True, nullable=False)
    api_key:      Mapped[str] = mapped_column(String, unique=True, nullable=False)
    agent_url:    Mapped[str | None] = mapped_column(String, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions:  Mapped[list[AttackSession]] = relationship("AttackSession", back_populates="client")
    scenarios: Mapped[list[Scenario]]      = relationship("Scenario",      back_populates="client")


class Scenario(Base):
    __tablename__ = "scenarios"

    id:           Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    scenario_key: Mapped[str] = mapped_column(String, nullable=False)  # original YAML id field
    name:         Mapped[str] = mapped_column(String, nullable=False)
    input_json:   Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    expected_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    assertions:   Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    owasp_json:   Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source:           Mapped[str] = mapped_column(String, nullable=False, default="builtin")  # builtin | generated
    type:             Mapped[str] = mapped_column(String, nullable=False, default="agent_attack")
    evaluation_json:  Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    client_id:        Mapped[str | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    created_at:       Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    client:   Mapped[Client | None]       = relationship("Client", back_populates="scenarios")
    sessions: Mapped[list[AttackSession]] = relationship("AttackSession", back_populates="scenario")


class TestJob(Base):
    __tablename__ = "test_jobs"

    id:              Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    client_id:       Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False)
    agent_url:       Mapped[str] = mapped_column(String, nullable=False, default="")
    status:          Mapped[str] = mapped_column(String, nullable=False, default="running")
    scenario_count:  Mapped[int] = mapped_column(nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(nullable=False, default=0)
    max_concurrency: Mapped[int] = mapped_column(nullable=False, default=3)
    created_at:      Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at:    Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list[AttackSession]] = relationship("AttackSession", back_populates="job")


class AttackSession(Base):
    __tablename__ = "attack_sessions"

    id:           Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    client_id:    Mapped[str] = mapped_column(ForeignKey("clients.id"), nullable=False)
    scenario_id:  Mapped[str] = mapped_column(ForeignKey("scenarios.id"), nullable=False)
    job_id:       Mapped[str | None] = mapped_column(ForeignKey("test_jobs.id"), nullable=True)
    status:       Mapped[str] = mapped_column(String, nullable=False, default="pending")
    started_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    client:      Mapped[Client]   = relationship("Client",   back_populates="sessions")
    scenario:    Mapped[Scenario] = relationship("Scenario", back_populates="sessions")
    job:         Mapped[TestJob | None] = relationship("TestJob", back_populates="sessions")
    events:      Mapped[list[Event]]      = relationship("Event",      back_populates="session")
    evaluations: Mapped[list[Evaluation]] = relationship("Evaluation", back_populates="session")


class Event(Base):
    __tablename__ = "events"

    id:             Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    session_id:     Mapped[str]      = mapped_column(ForeignKey("attack_sessions.id"), nullable=False)
    attack_run_id:  Mapped[str|None] = mapped_column(String, nullable=True, default=None, index=True)
    tool_name:      Mapped[str]      = mapped_column(String, nullable=False, default="")
    tool_args:      Mapped[str]      = mapped_column(Text, nullable=False, default="{}")
    tool_result:    Mapped[str|None] = mapped_column(Text, nullable=True, default=None)
    executed:       Mapped[bool]     = mapped_column(Boolean, nullable=False, default=False)
    phase:          Mapped[str]      = mapped_column(String, nullable=False, default="")
    timestamp:      Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped[AttackSession] = relationship("AttackSession", back_populates="events")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id:          Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id:  Mapped[str] = mapped_column(ForeignKey("attack_sessions.id"), nullable=False)
    method:      Mapped[str] = mapped_column(String, nullable=False, default="llm")
    result_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped[AttackSession] = relationship("AttackSession", back_populates="evaluations")
