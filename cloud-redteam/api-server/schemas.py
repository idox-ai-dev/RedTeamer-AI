from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ── Clients ────────────────────────────────────────────────────────

class ClientRegister(BaseModel):
    name: str
    agent_url: Optional[str] = None

class ClientOut(BaseModel):
    id: str
    name: str
    api_key: str
    agent_url: Optional[str]
    registered_at: datetime
    last_seen: Optional[datetime]
    model_config = {"from_attributes": True}

class ClientUpdate(BaseModel):
    agent_url: Optional[str] = None


# ── Scenarios ──────────────────────────────────────────────────────

class ScenarioOut(BaseModel):
    id: str
    scenario_key: str
    name: str
    input_json: str
    expected_json: str
    assertions: str
    owasp_json: str
    source: str
    type: str = "agent_attack"
    evaluation_json: str = "{}"
    client_id: Optional[str]
    created_at: datetime
    model_config = {"from_attributes": True}

class ScenarioCreate(BaseModel):
    scenario_key: str
    name: str
    input_json: str
    expected_json: str = '{"decision":"block"}'
    assertions: str = '["tool_call_captured","unsafe_action_not_executed"]'
    owasp_json: str = "[]"
    type: str = "agent_attack"
    evaluation_json: str = "{}"

class ScenarioGenerateRequest(BaseModel):
    query: str
    count: int = 1


# ── Test Jobs ──────────────────────────────────────────────────────

class TestJobCreate(BaseModel):
    agent_url: str
    scenario_ids: List[str]
    openclaw_session_id: Optional[str] = None
    max_concurrency: int = 3

class SessionSummary(BaseModel):
    id: str
    scenario_id: str
    scenario_key: str
    scenario_name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    evaluation: Optional[Dict[str, Any]] = None
    assertions: List[str] = []
    owasp_mapping: List[str] = []
    evaluation_guidance: str = ""

class TestJobOut(BaseModel):
    id: str
    client_id: str
    agent_url: str
    status: str
    scenario_count: int
    completed_count: int
    max_concurrency: int = 3
    created_at: datetime
    completed_at: Optional[datetime]
    model_config = {"from_attributes": True}

class TestJobDetailOut(TestJobOut):
    sessions: List[SessionSummary] = []


# ── Attacks ────────────────────────────────────────────────────────

class AttackTriggerRequest(BaseModel):
    scenario_id: str
    openclaw_session_id: Optional[str] = None

class AutoIterateRequest(BaseModel):
    scenario_id: str
    openclaw_session_id: Optional[str] = None
    max_iterations: int = 3

class AttackSessionOut(BaseModel):
    id: str
    client_id: str
    scenario_id: str
    scenario_type: str = "agent_attack"
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    model_config = {"from_attributes": True}


# ── Events ─────────────────────────────────────────────────────────

class EventIn(BaseModel):
    tool_name: str = ""
    tool_args: Dict[str, Any] = {}
    tool_result: Optional[Any] = None
    attack_run_id: Optional[str] = None
    executed: bool = False
    phase: str = ""
    timestamp: Optional[str] = None

class EventBatchIn(BaseModel):
    session_id: str
    events: List[EventIn]

class EventOut(BaseModel):
    id: int
    session_id: str
    attack_run_id: Optional[str] = None
    tool_name: str
    tool_args: str
    tool_result: Optional[str] = None
    executed: bool
    phase: str
    timestamp: datetime
    model_config = {"from_attributes": True}


# ── Evaluations ────────────────────────────────────────────────────

class EvaluationRequest(BaseModel):
    session_id: str
    method: str = "llm"  # rule | llm

class EvaluationOut(BaseModel):
    id: str
    session_id: str
    method: str
    result_json: str
    created_at: datetime
    model_config = {"from_attributes": True}
