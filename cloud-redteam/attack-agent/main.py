#!/usr/bin/env python3
"""OpenClaw Red Team — Attack Agent (runs on attacker host)"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

import cli_adapter
import event_forwarder

_base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
load_dotenv(_base_dir / '.env')

CLOUD_API_URL   = os.environ.get("CLOUD_API_URL", "http://localhost:8000")
AGENT_API_KEY   = os.environ.get("AGENT_API_KEY", "")
AGENT_HOST_URL  = os.environ.get("AGENT_HOST_URL", "http://localhost:9000")

# ── Logging ────────────────────────────────────────────────────────
_log_dir = Path(os.environ.get("LOG_DIR", str(_base_dir / "logs")))
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            _log_dir / "attack-agent.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)

app = FastAPI(title="OpenClaw Red Team Attack Agent", version="0.1.0")


# ── Schemas ────────────────────────────────────────────────────────

class AttackPayload(BaseModel):
    session_id: str
    scenario_key: str
    openclaw_session_id: str = ""
    user_goal: str
    injected_instruction: str = ""
    safety_mode: bool = True
    dry_run: bool = True
    type: str = "agent_attack"


# ── Endpoints ──────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "agent_url": AGENT_HOST_URL}


@app.post("/attack")
def run_attack(payload: AttackPayload):
    threading.Thread(
        target=_execute_attack,
        args=(payload,),
        daemon=True,
    ).start()
    return {"ok": True, "session_id": payload.session_id, "message": "Attack started in background"}


# ── Core attack logic ──────────────────────────────────────────────

def _collect_with_polling(
    before_ts: str,
    run_id: str,
    oc_session: str | None = None,
    stable_checks: int = 2,
    interval: float = 0.5,
    timeout: float = 15.0,
) -> list:
    deadline = time.time() + timeout
    last_count = -1
    stable = 0
    while time.time() < deadline:
        events = event_forwarder.collect(before_ts, run_id=run_id, oc_session=oc_session)
        if len(events) == last_count:
            stable += 1
            if stable >= stable_checks:
                log.info("[collect_polling] stable at %d events after %.1fs",
                         len(events), timeout - (deadline - time.time()))
                return events
        else:
            stable = 0
            last_count = len(events)
        time.sleep(interval)
    events = event_forwarder.collect(before_ts, run_id=run_id, oc_session=oc_session)
    log.warning("[collect_polling] timeout reached, returning %d events", len(events))
    return events


def _execute_attack(payload: AttackPayload) -> None:
    _run_agent_attack(payload)


def _run_agent_attack(payload: AttackPayload) -> None:
    import pathlib

    session_id = payload.session_id
    message    = payload.user_goal
    if payload.injected_instruction:
        message = f"{message}\n\n{payload.injected_instruction}"

    raw_session = payload.openclaw_session_id or payload.scenario_key
    oc_session = raw_session.replace(" ", "-")

    before_ts = datetime.now(timezone.utc).isoformat()
    log.info("[%s] Starting attack: %s…", session_id, message[:80])

    # Register this attack's run_id with the observer so all events are tagged
    event_forwarder.start_run(session_id, oc_session)

    # Clear stale openclaw session history so the model starts fresh each run
    session_file = pathlib.Path.home() / ".openclaw" / "agents" / "main" / "sessions" / f"{oc_session}.jsonl"
    if session_file.exists():
        session_file.unlink()
        log.info("[%s] Cleared stale session file: %s", session_id, session_file.name)

    result = cli_adapter.run(oc_session, message)
    if result.timed_out:
        log.warning("[%s] openclaw timed out", session_id)
    elif result.returncode != 0:
        log.error("[%s] openclaw exit=%d stderr=%s", session_id, result.returncode, result.stderr[:200])
    else:
        log.info("[%s] openclaw exit=0", session_id)

    events = _collect_with_polling(before_ts, run_id=session_id, oc_session=oc_session)
    event_forwarder.end_run(oc_session)

    eval_events = event_forwarder.filter_for_evaluation(events)
    if len(eval_events) != len(events):
        log.info("[%s] Pre-eval filter: %d → %d events (removed %d startup/config reads)",
                 session_id, len(events), len(eval_events), len(events) - len(eval_events))

    # Detect Azure content filter blocks and inject a synthetic event so evaluators
    # can distinguish "filter blocked it" from "nothing happened"
    _FILTER_KEYWORDS = ("content_filter", "ContentPolicyViolation",
                        "ResponsibleAIPolicyViolation", "jailbreak")
    combined_output = ((result.stderr or "") + (result.stdout or "")).lower()
    if not events and result.returncode != 0 and any(k.lower() in combined_output for k in _FILTER_KEYWORDS):
        events = [{
            "tool_name":     "content_filter_blocked",
            "tool_args":     {"reason": "Azure content filter blocked the prompt (jailbreak detected)"},
            "executed":      False,
            "phase":         "content_filter",
            "attack_run_id": session_id,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
        }]
        log.warning("[%s] Content filter detected — injecting synthetic event", session_id)

    log.info("[%s] Collected %d events", session_id, len(events))

    status = event_forwarder.forward(session_id, eval_events, AGENT_API_KEY)
    if status:
        log.info("[cloud] Events forwarded: %s", status)

    _complete_session(session_id)


def _complete_session(session_id: str) -> None:
    if not AGENT_API_KEY:
        return
    try:
        requests.patch(
            f"{CLOUD_API_URL}/api/v1/attacks/{session_id}/complete",
            headers={"X-API-Key": AGENT_API_KEY},
            timeout=10,
        )
    except Exception as e:
        log.error("[cloud] Complete error: %s", e)


# ── Auto-registration on startup ───────────────────────────────────

@app.on_event("startup")
def auto_register():
    client_name  = os.environ.get("CLIENT_NAME", "")
    admin_token  = os.environ.get("ADMIN_TOKEN", "")
    if not client_name or not admin_token or not CLOUD_API_URL:
        log.info("[agent] Skipping auto-registration (CLIENT_NAME / ADMIN_TOKEN / CLOUD_API_URL not set)")
        return

    try:
        resp = requests.post(
            f"{CLOUD_API_URL}/api/v1/clients/register",
            json={"name": client_name, "agent_url": AGENT_HOST_URL},
            headers={"X-Admin-Token": admin_token},
            timeout=10,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            api_key = data.get("api_key", "")
            log.info("[agent] Registered as '%s'. API key written to env — use it to log in to the Web UI.", client_name)
        elif resp.status_code == 409:
            log.warning("[agent] Client '%s' already registered. Use existing API key.", client_name)
        else:
            log.error("[agent] Registration failed: %s %s", resp.status_code, resp.text[:100])
    except Exception as e:
        log.error("[agent] Registration error: %s", e)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.environ.get("AGENT_HOST", "0.0.0.0"),
        port=int(os.environ.get("AGENT_PORT", "9000")),
        reload=False,
    )
