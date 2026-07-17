from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List

_CONCURRENCY_CAP = int(os.environ.get("DEFAULT_MAX_CONCURRENCY", "3"))

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update as sql_update
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

    requested = body.max_concurrency or _CONCURRENCY_CAP
    max_concurrency = max(1, min(requested, _CONCURRENCY_CAP))

    job = TestJob(
        client_id=current.id,
        agent_url=body.agent_url,
        status="running",
        scenario_count=len(body.scenario_ids),
        completed_count=0,
        max_concurrency=max_concurrency,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    log.info("Job created: job=%s scenarios=%d concurrency=%d agent=%s",
             job.id, len(body.scenario_ids), max_concurrency, body.agent_url)

    threading.Thread(
        target=_run_job,
        args=(job.id, current.id, body.agent_url, body.scenario_ids, max_concurrency, body.openclaw_session_id),
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
        max_concurrency=job.max_concurrency,
        created_at=job.created_at,
        completed_at=job.completed_at,
        sessions=[_build_session_summary(s) for s in sessions],
    )


def _run_single_scenario(
    job_id: str,
    client_id: str,
    agent_url: str,
    scenario_id: str,
    openclaw_session_id: str | None,
    failed_event: threading.Event,
    idx: int,
    total: int,
) -> None:
    db = SessionLocal()
    tag = f"[job {job_id[:8]}]"
    try:
        sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
        if not sc:
            log.warning("%s Scenario %s not found, skipping", tag, scenario_id)
            failed_event.set()
            return

        tag = f"[job {job_id[:8]}][{sc.scenario_key}]"
        log.info("%s [%d/%d] Running scenario", tag, idx, total)

        # ── 1. Create session ─────────────────────────────────────────
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
            "openclaw_session_id":  sc.scenario_key,  # must be unique per scenario for parallel safety
            "user_goal":            sc_input.get("user_goal", ""),
            "injected_instruction": sc_input.get("injected_instruction", ""),
            "safety_mode":          True,
            "dry_run":              True,
            "type":                 getattr(sc, "type", "agent_attack"),
        }

        # ── 2. Dispatch to agent ──────────────────────────────────────
        log.info("%s Dispatching session=%s to agent", tag, session.id)
        try:
            resp = httpx.post(agent_url.rstrip("/") + "/attack", json=payload, timeout=15)
            if resp.status_code >= 400:
                session.status = "failed"
                db.commit()
                failed_event.set()
                log.error("%s Agent error %d", tag, resp.status_code)
                return
        except Exception as e:
            session.status = "failed"
            db.commit()
            failed_event.set()
            log.error("%s Cannot reach agent: %s", tag, e)
            return

        # ── 3. Poll until session completed (max 150 s) ───────────────
        for _ in range(50):
            time.sleep(3)
            db.expire(session)
            db.refresh(session)
            if session.status in ("completed", "failed"):
                break

        if session.status != "completed":
            session.status = "failed"
            db.commit()
            failed_event.set()
            log.warning("%s Session timed out", tag)
            return

        log.info("%s Session completed: %s", tag, session.id)

        # ── 4. LLM evaluate ───────────────────────────────────────────
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
            log.info("%s Evaluating session=%s (%d events)", tag, session.id, len(raw_events))
            from services.llm_service import evaluate_with_llm
            result = asyncio.run(evaluate_with_llm(scenario_dict, raw_events))
            ev = Evaluation(session_id=session.id, method="llm", result_json=json.dumps(result))
            db.add(ev)
            db.commit()
            log.info("%s Evaluation done → %s", tag, result.get("status"))
        except Exception as e:
            log.error("%s Evaluation failed: %s", tag, e)

        # ── 5. Atomic progress update ─────────────────────────────────
        db.execute(
            sql_update(TestJob)
            .where(TestJob.id == job_id)
            .values(completed_count=TestJob.completed_count + 1)
        )
        db.commit()

    except Exception as e:
        log.error("%s Unexpected error: %s", tag, e)
        failed_event.set()
    finally:
        db.close()


def _run_job(
    job_id: str,
    client_id: str,
    agent_url: str,
    scenario_ids: list[str],
    max_concurrency: int = 3,
    openclaw_session_id: str | None = None,
) -> None:
    db = SessionLocal()
    try:
        job = db.query(TestJob).filter(TestJob.id == job_id).first()
        if not job:
            return

        log.info("[job %s] Starting — %d scenarios, concurrency=%d", job_id[:8], len(scenario_ids), max_concurrency)
        failed_event = threading.Event()

        with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
            futures = {
                executor.submit(
                    _run_single_scenario,
                    job_id, client_id, agent_url, scenario_id,
                    openclaw_session_id, failed_event,
                    idx, len(scenario_ids),
                ): scenario_id
                for idx, scenario_id in enumerate(scenario_ids, 1)
            }
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log.error("[job %s] Scenario future raised: %s", job_id[:8], e)
                    failed_event.set()

        db.expire(job)
        db.refresh(job)
        job.status = "failed" if failed_event.is_set() else "completed"
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
