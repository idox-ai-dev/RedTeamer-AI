from __future__ import annotations

import json
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_client
from database import get_db
from models_db import AttackSession, Client, Evaluation, Event, Scenario
from schemas import EvaluationOut, EvaluationRequest, ScenarioOut

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
log = logging.getLogger(__name__)


@router.post("/", response_model=EvaluationOut)
async def create_evaluation(
    body: EvaluationRequest,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    session = db.query(AttackSession).filter(
        AttackSession.id == body.session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    sc = db.query(Scenario).filter(Scenario.id == session.scenario_id).first()
    events = db.query(Event).filter(Event.session_id == body.session_id).all()

    log.info("Evaluating session=%s method=%s events=%d", body.session_id, body.method, len(events))

    raw_events = [
        {
            "tool_name":   e.tool_name,
            "tool_args":   json.loads(e.tool_args),
            "tool_result": json.loads(e.tool_result) if e.tool_result else None,
            "executed":    e.executed,
            "phase":       e.phase,
            "timestamp":   e.timestamp.isoformat(),
        }
        for e in events
    ]

    scenario_dict = {
        "id":           sc.scenario_key,
        "name":         sc.name,
        "input":        json.loads(sc.input_json),
        "expected":     json.loads(sc.expected_json),
        "assertions":   json.loads(sc.assertions),
        "owasp_mapping": json.loads(sc.owasp_json),
        "type":       getattr(sc, "type", "agent_attack"),
        "evaluation": json.loads(getattr(sc, "evaluation_json", "{}")),
    }

    method = body.method.lower()
    if method == "rule":
        from evaluators.rule_evaluator import evaluate
        result = evaluate(scenario_dict, raw_events)
    else:
        from services.llm_service import evaluate_with_llm
        result = await evaluate_with_llm(scenario_dict, raw_events)

    ev = Evaluation(
        session_id=body.session_id,
        method=method,
        result_json=json.dumps(result),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    log.info("Evaluation complete: session=%s status=%s attack_successful=%s",
             body.session_id, result.get("status"), result.get("attack_successful"))
    return ev


@router.get("/", response_model=List[EvaluationOut])
def list_evaluations(
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    session_ids = [
        s.id for s in db.query(AttackSession).filter(AttackSession.client_id == current.id).all()
    ]
    if not session_ids:
        return []
    return db.query(Evaluation).filter(Evaluation.session_id.in_(session_ids)).all()


@router.post("/{evaluation_id}/refine", response_model=ScenarioOut)
async def refine_scenario(
    evaluation_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    ev = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    session = db.query(AttackSession).filter(
        AttackSession.id == ev.session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not session:
        raise HTTPException(status_code=403, detail="Not your evaluation")

    result = json.loads(ev.result_json)
    if result.get("attack_successful") is True:
        raise HTTPException(status_code=400, detail="Attack was successful — no refinement needed")

    sc = db.query(Scenario).filter(Scenario.id == session.scenario_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Original scenario not found")

    log.info("Refining scenario: original=%s evaluation=%s", sc.scenario_key, evaluation_id)

    scenario_dict = {
        "id":           sc.scenario_key,
        "name":         sc.name,
        "input":        json.loads(sc.input_json),
        "expected":     json.loads(sc.expected_json),
        "assertions":   json.loads(sc.assertions),
        "owasp_mapping": json.loads(sc.owasp_json),
        "type":       getattr(sc, "type", "agent_attack"),
        "evaluation": json.loads(getattr(sc, "evaluation_json", "{}")),
    }

    from services.llm_service import generate_scenario_from_evaluation
    generated = await generate_scenario_from_evaluation(scenario_dict, result)

    new_sc = Scenario(
        scenario_key=generated.get("id", f"ASI-REFINED-{sc.scenario_key}"),
        name=generated.get("name", f"[Refined] {sc.name}"),
        input_json=json.dumps(generated.get("input", {})),
        expected_json=json.dumps(generated.get("expected", {"decision": "block"})),
        assertions=json.dumps(generated.get("assertions", ["tool_call_captured", "unsafe_action_not_executed"])),
        owasp_json=json.dumps(generated.get("owasp_mapping", json.loads(sc.owasp_json))),
        evaluation_json=json.dumps(generated.get("evaluation", {})),
        source="generated",
        client_id=current.id,
    )
    db.add(new_sc)
    db.commit()
    db.refresh(new_sc)
    try:
        from services.scenario_io import save_scenario_yaml
        save_scenario_yaml(new_sc)
    except Exception as e:
        log.warning("Failed to save YAML for %s: %s", new_sc.scenario_key, e)
    log.info("Scenario refined: original=%s → new=%s", sc.scenario_key, new_sc.scenario_key)
    return new_sc


@router.get("/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(
    evaluation_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    ev = db.query(Evaluation).filter(Evaluation.id == evaluation_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    session = db.query(AttackSession).filter(
        AttackSession.id == ev.session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not session:
        raise HTTPException(status_code=403, detail="Not your evaluation")
    return ev
