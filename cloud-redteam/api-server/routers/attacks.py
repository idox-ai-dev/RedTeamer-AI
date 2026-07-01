from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import List

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_client
from database import get_db, SessionLocal
from models_db import AttackSession, Client, Evaluation, Event, Scenario
from schemas import AttackSessionOut, AttackTriggerRequest, AutoIterateRequest

router = APIRouter(prefix="/attacks", tags=["attacks"])
log = logging.getLogger(__name__)


@router.post("/trigger", response_model=AttackSessionOut)
async def trigger_attack(
    body: AttackTriggerRequest,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    if not current.agent_url:
        raise HTTPException(status_code=400,
                            detail="No agent_url registered. Update your client first.")

    sc = db.query(Scenario).filter(Scenario.id == body.scenario_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if sc.source == "generated" and sc.client_id != current.id:
        raise HTTPException(status_code=403, detail="Not your scenario")

    session = AttackSession(
        client_id=current.id,
        scenario_id=sc.id,
        status="running",
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    log.info("Triggering attack: scenario=%s session=%s agent=%s", sc.scenario_key, session.id, current.agent_url)

    sc_input = json.loads(sc.input_json)
    payload = {
        "session_id":           session.id,
        "scenario_key":         sc.scenario_key,
        "openclaw_session_id":  body.openclaw_session_id or sc.scenario_key,
        "user_goal":            sc_input.get("user_goal", ""),
        "injected_instruction": sc_input.get("injected_instruction", ""),
        "safety_mode":          True,
        "dry_run":              True,
        "type":                 getattr(sc, "type", "agent_attack"),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client_http:
            resp = await client_http.post(
                current.agent_url.rstrip("/") + "/attack",
                json=payload,
            )
        if resp.status_code >= 400:
            session.status = "failed"
            db.commit()
            log.error("Agent returned %d for session=%s: %s", resp.status_code, session.id, resp.text[:200])
            raise HTTPException(status_code=502,
                                detail=f"Agent returned {resp.status_code}: {resp.text[:200]}")
    except httpx.RequestError as e:
        session.status = "failed"
        db.commit()
        log.error("Cannot reach agent %s: %s", current.agent_url, e)
        raise HTTPException(status_code=502, detail=f"Cannot reach agent: {e}")

    log.info("Attack dispatched: session=%s", session.id)
    return session


@router.post("/auto-iterate")
async def auto_iterate(
    body: AutoIterateRequest,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    if not current.agent_url:
        raise HTTPException(status_code=400, detail="No agent_url registered.")

    sc = db.query(Scenario).filter(Scenario.id == body.scenario_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if sc.source == "generated" and sc.client_id != current.id:
        raise HTTPException(status_code=403, detail="Not your scenario")

    max_iter = max(1, min(body.max_iterations, 10))
    log.info("Auto-iterate started: scenario=%s max_iter=%d agent=%s", sc.scenario_key, max_iter, current.agent_url)

    threading.Thread(
        target=_auto_iterate_loop,
        args=(current.id, current.agent_url, sc.id, body.openclaw_session_id, max_iter),
        daemon=True,
    ).start()

    return {"ok": True, "message": f"Auto-iterate started (max {max_iter} iterations)"}


def _auto_iterate_loop(client_id: str, agent_url: str, scenario_id: str,
                       openclaw_session_id: str | None, max_iterations: int) -> None:
    db = SessionLocal()
    try:
        current_scenario_id = scenario_id

        for iteration in range(1, max_iterations + 1):
            log.info("[auto-iterate] ── Iteration %d/%d ──", iteration, max_iterations)

            sc = db.query(Scenario).filter(Scenario.id == current_scenario_id).first()
            if not sc:
                log.warning("[auto-iterate] Scenario not found, stopping")
                break

            # ── 1. Create session & dispatch to agent ──────────────
            session = AttackSession(client_id=client_id, scenario_id=sc.id, status="running")
            db.add(session)
            db.commit()
            db.refresh(session)

            sc_input = json.loads(sc.input_json)
            payload = {
                "session_id":           session.id,
                "scenario_key":         sc.scenario_key,
                "openclaw_session_id":  openclaw_session_id or sc.scenario_key,
                "user_goal":            sc_input.get("user_goal", ""),
                "injected_instruction": sc_input.get("injected_instruction", ""),
                "safety_mode":          True,
                "dry_run":              True,
                "type":                 getattr(sc, "type", "agent_attack"),
            }
            log.info("[auto-iterate] Dispatching session=%s to agent", session.id)
            try:
                resp = httpx.post(agent_url.rstrip("/") + "/attack", json=payload, timeout=10)
                if resp.status_code >= 400:
                    session.status = "failed"
                    db.commit()
                    log.error("[auto-iterate] Agent error %d, stopping", resp.status_code)
                    break
            except Exception as e:
                session.status = "failed"
                db.commit()
                log.error("[auto-iterate] Cannot reach agent: %s, stopping", e)
                break

            # ── 2. Poll until completed (max 150 s) ────────────────
            for _ in range(50):
                time.sleep(3)
                db.expire(session)
                db.refresh(session)
                if session.status in ("completed", "failed"):
                    break

            if session.status != "completed":
                log.warning("[auto-iterate] Session %s timed out, stopping", session.id)
                break

            # ── 3. Evaluate ────────────────────────────────────────
            events = db.query(Event).filter(Event.session_id == session.id).all()
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
                "evaluation":   json.loads(getattr(sc, "evaluation_json", "{}")),
            }

            from services.llm_service import evaluate_with_llm
            result = asyncio.run(evaluate_with_llm(scenario_dict, raw_events))

            ev = Evaluation(session_id=session.id, method="llm", result_json=json.dumps(result))
            db.add(ev)
            db.commit()

            succeeded = result.get("attack_successful", False)
            status_label = result.get("status", "FAILED")
            log.info("[auto-iterate] Iteration %d: %s", iteration, status_label)

            # ── 4. Stop if attack succeeded or last iteration ──────
            if succeeded or iteration >= max_iterations:
                log.info("[auto-iterate] Stopping after iteration %d", iteration)
                break

            # ── 5. Refine scenario for next iteration ──────────────
            from services.llm_service import generate_scenario_from_evaluation
            from services.scenario_io import save_scenario_yaml
            try:
                generated = asyncio.run(generate_scenario_from_evaluation(scenario_dict, result))
                new_sc = Scenario(
                    scenario_key=generated.get("id", f"ASI-AUTO-ITER{iteration+1}"),
                    name=generated.get("name", f"[Auto iter {iteration+1}] {sc.name}"),
                    input_json=json.dumps(generated.get("input", {})),
                    expected_json=json.dumps(generated.get("expected", {"decision": "block"})),
                    assertions=json.dumps(generated.get("assertions", ["tool_call_captured", "unsafe_action_not_executed"])),
                    owasp_json=json.dumps(generated.get("owasp_mapping", json.loads(sc.owasp_json))),
                    evaluation_json=json.dumps(generated.get("evaluation", {})),
                    source="generated",
                    client_id=client_id,
                )
                db.add(new_sc)
                db.commit()
                db.refresh(new_sc)
                try:
                    save_scenario_yaml(new_sc)
                except Exception:
                    pass
                current_scenario_id = new_sc.id
                log.info("[auto-iterate] Refined → %s", new_sc.scenario_key)
            except Exception as e:
                log.error("[auto-iterate] Refinement failed: %s, stopping", e)
                break

    except Exception as e:
        log.error("[auto-iterate] Unexpected error: %s", e)
    finally:
        db.close()
        log.info("[auto-iterate] Loop finished")


@router.get("/", response_model=List[AttackSessionOut])
def list_sessions(
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    sessions = db.query(AttackSession).filter(AttackSession.client_id == current.id).all()
    for s in sessions:
        s.scenario_type = s.scenario.type if s.scenario else "agent_attack"
    return sessions


@router.get("/{session_id}", response_model=AttackSessionOut)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    s = db.query(AttackSession).filter(
        AttackSession.id == session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s.scenario_type = s.scenario.type if s.scenario else "agent_attack"
    return s


@router.patch("/{session_id}/complete")
def complete_session(
    session_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    s = db.query(AttackSession).filter(
        AttackSession.id == session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    s.status = "completed"
    s.completed_at = datetime.now(timezone.utc)
    db.commit()
    log.info("Session completed: %s", session_id)
    return {"ok": True}
