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
from models_db import AttackSession, Client, Evaluation, Event, Scenario, TestJob
from schemas import TestJobCreate, TestJobDetailOut, TestJobOut, SessionSummary

router = APIRouter(prefix="/jobs", tags=["jobs"])
log = logging.getLogger(__name__)


def _build_session_summary(session: AttackSession) -> SessionSummary:
    sc = session.scenario
    ev = session.evaluations[-1] if session.evaluations else None
    evaluation = json.loads(ev.result_json) if ev else None
    assertions: list[str] = json.loads(sc.assertions) if sc and sc.assertions else []
    owasp_mapping: list[str] = json.loads(sc.owasp_json) if sc and sc.owasp_json else []
    evaluation_guidance = ""
    if sc and sc.evaluation_json:
        try:
            evaluation_guidance = json.loads(sc.evaluation_json).get("guidance", "")
        except Exception:
            pass
    return SessionSummary(
        id=session.id,
        scenario_id=session.scenario_id,
        scenario_key=sc.scenario_key if sc else "",
        scenario_name=sc.name if sc else "",
        status=session.status,
        started_at=session.started_at,
        completed_at=session.completed_at,
        evaluation=evaluation,
        assertions=assertions,
        owasp_mapping=owasp_mapping,
        evaluation_guidance=evaluation_guidance,
    )


@router.post("/", response_model=TestJobOut)
async def create_job(
    body: TestJobCreate,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    if not body.scenario_ids:
        raise HTTPException(status_code=400, detail="scenario_ids must not be empty")
    if not body.agent_url:
        raise HTTPException(status_code=400, detail="agent_url is required")

    scenarios = db.query(Scenario).filter(Scenario.id.in_(body.scenario_ids)).all()
    found_ids = {sc.id for sc in scenarios}
    missing = [sid for sid in body.scenario_ids if sid not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Scenarios not found: {missing}")

    job = TestJob(
        client_id=current.id,
        agent_url=body.agent_url,
        status="running",
        scenario_count=len(body.scenario_ids),
        completed_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    log.info("Job created: job=%s scenarios=%d agent=%s", job.id, len(body.scenario_ids), body.agent_url)

    threading.Thread(
        target=_run_job,
        args=(job.id, current.id, body.agent_url, body.scenario_ids, body.openclaw_session_id),
        daemon=True,
    ).start()

    return job


@router.get("/", response_model=List[TestJobOut])
def list_jobs(
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    return db.query(TestJob).filter(
        TestJob.client_id == current.id
    ).order_by(TestJob.created_at.desc()).all()


@router.get("/{job_id}", response_model=TestJobDetailOut)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    job = db.query(TestJob).filter(
        TestJob.id == job_id,
        TestJob.client_id == current.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sessions = db.query(AttackSession).filter(
        AttackSession.job_id == job_id
    ).order_by(AttackSession.started_at).all()

    return TestJobDetailOut(
        id=job.id,
        client_id=job.client_id,
        agent_url=job.agent_url,
        status=job.status,
        scenario_count=job.scenario_count,
        completed_count=job.completed_count,
        created_at=job.created_at,
        completed_at=job.completed_at,
        sessions=[_build_session_summary(s) for s in sessions],
    )


def _run_job(job_id: str, client_id: str, agent_url: str, scenario_ids: list[str], openclaw_session_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.query(TestJob).filter(TestJob.id == job_id).first()
        if not job:
            return

        log.info("[job %s] Starting — %d scenarios", job_id[:8], len(scenario_ids))
        any_failed = False

        for idx, scenario_id in enumerate(scenario_ids, 1):
            sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
            if not sc:
                log.warning("[job %s] Scenario %s not found, skipping", job_id[:8], scenario_id)
                any_failed = True
                continue

            log.info("[job %s] [%d/%d] Running scenario: %s", job_id[:8], idx, len(scenario_ids), sc.scenario_key)

            # ── 1. Create session ─────────────────────────────────────
            session = AttackSession(
                client_id=client_id,
                scenario_id=sc.id,
                job_id=job_id,
                status="running",
            )
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

            # ── 2. Dispatch to agent ───────────────────────────────────
            log.info("[job %s] Dispatching session=%s to agent", job_id[:8], session.id)
            try:
                resp = httpx.post(agent_url.rstrip("/") + "/attack", json=payload, timeout=15)
                if resp.status_code >= 400:
                    session.status = "failed"
                    db.commit()
                    any_failed = True
                    log.error("[job %s] Agent error %d for %s", job_id[:8], resp.status_code, sc.scenario_key)
                    continue
            except Exception as e:
                session.status = "failed"
                db.commit()
                any_failed = True
                log.error("[job %s] Cannot reach agent: %s", job_id[:8], e)
                continue

            # ── 3. Poll until session completed (max 150 s) ───────────
            for _ in range(50):
                time.sleep(3)
                db.expire(session)
                db.refresh(session)
                if session.status in ("completed", "failed"):
                    break

            if session.status != "completed":
                session.status = "failed"
                db.commit()
                any_failed = True
                log.warning("[job %s] Session timed out for %s", job_id[:8], sc.scenario_key)
                continue

            log.info("[job %s] Session completed: %s", job_id[:8], session.id)

            # ── 4. LLM evaluate ────────────────────────────────────────
            try:
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
                    "id":            sc.scenario_key,
                    "name":          sc.name,
                    "input":         json.loads(sc.input_json),
                    "expected":      json.loads(sc.expected_json),
                    "assertions":    json.loads(sc.assertions),
                    "owasp_mapping": json.loads(sc.owasp_json),
                    "evaluation":    json.loads(getattr(sc, "evaluation_json", "{}")),
                }
                log.info("[job %s] Evaluating session=%s (%d events)", job_id[:8], session.id, len(raw_events))
                from services.llm_service import evaluate_with_llm
                result = asyncio.run(evaluate_with_llm(scenario_dict, raw_events))
                ev = Evaluation(session_id=session.id, method="llm", result_json=json.dumps(result))
                db.add(ev)
                db.commit()
                log.info("[job %s] Evaluation done: %s → %s", job_id[:8], sc.scenario_key, result.get("status"))
            except Exception as e:
                log.error("[job %s] Evaluation failed for %s: %s", job_id[:8], sc.scenario_key, e)

            # ── 5. Advance job progress ────────────────────────────────
            db.expire(job)
            db.refresh(job)
            job.completed_count = (job.completed_count or 0) + 1
            db.commit()

        # ── Mark job done ─────────────────────────────────────────────
        db.expire(job)
        db.refresh(job)
        job.status = "failed" if any_failed else "completed"
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
        log.info("[job %s] Finished — status=%s", job_id[:8], job.status)

    except Exception as e:
        log.error("[job %s] Unexpected error: %s", job_id[:8], e)
        try:
            db.expire(job)
            db.refresh(job)
            job.status = "failed"
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            pass
    finally:
        db.close()
