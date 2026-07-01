from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_client
from database import get_db
from models_db import AttackSession, Client, Event
from schemas import EventBatchIn, EventOut

router = APIRouter(prefix="/events", tags=["events"])
log = logging.getLogger(__name__)


@router.post("/batch")
def ingest_events(
    body: EventBatchIn,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    session = db.query(AttackSession).filter(
        AttackSession.id == body.session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    log.info("Ingesting %d events for session=%s", len(body.events), body.session_id)

    for ev in body.events:
        ts = None
        if ev.timestamp:
            try:
                ts = datetime.fromisoformat(ev.timestamp.rstrip("Z"))
            except ValueError:
                ts = None
        tool_result_str = None
        if ev.tool_result is not None:
            tool_result_str = json.dumps(ev.tool_result) if not isinstance(ev.tool_result, str) else ev.tool_result
        event = Event(
            session_id=body.session_id,
            attack_run_id=ev.attack_run_id,
            tool_name=ev.tool_name,
            tool_args=json.dumps(ev.tool_args),
            tool_result=tool_result_str,
            executed=ev.executed,
            phase=ev.phase,
            timestamp=ts or datetime.utcnow(),
        )
        db.add(event)
    db.commit()
    log.info("Events ingested: session=%s count=%d", body.session_id, len(body.events))
    return {"ok": True, "count": len(body.events)}


@router.get("/{session_id}", response_model=List[EventOut])
def get_events(
    session_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    session = db.query(AttackSession).filter(
        AttackSession.id == session_id,
        AttackSession.client_id == current.id,
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return db.query(Event).filter(Event.session_id == session_id).all()
