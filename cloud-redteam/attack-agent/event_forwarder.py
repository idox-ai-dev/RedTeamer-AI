from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

OBSERVER_URL  = os.environ.get("OBSERVER_URL", "http://127.0.0.1:18790")
CLOUD_API_URL = os.environ.get("CLOUD_API_URL", "http://localhost:8000")

log = logging.getLogger(__name__)


def clear_events() -> None:
    try:
        requests.delete(f"{OBSERVER_URL}/events", timeout=5)
    except Exception:
        pass


def start_run(run_id: str) -> None:
    log.info("[event_forwarder] Starting run: %s → %s/run/start", run_id, OBSERVER_URL)
    try:
        requests.post(f"{OBSERVER_URL}/run/start", json={"run_id": run_id}, timeout=5)
        log.info("[event_forwarder] Run started: %s", run_id)
    except Exception as exc:
        log.error("[event_forwarder] start_run error: %s", exc)


def end_run() -> None:
    try:
        requests.post(f"{OBSERVER_URL}/run/end", timeout=5)
        log.info("[event_forwarder] Run ended")
    except Exception:
        pass


def collect(since_iso: str, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    log.info("[event_forwarder] Collecting events from %s since=%s run_id=%s", OBSERVER_URL, since_iso, run_id)
    try:
        params = f"since={since_iso}"
        if run_id:
            params += f"&attack_run_id={run_id}"
        r = requests.get(f"{OBSERVER_URL}/events?{params}", timeout=8)
        if not r.ok:
            log.warning("[event_forwarder] Collect returned HTTP %d", r.status_code)
            return []
        raw = r.json()
        if isinstance(raw, list):
            events = [e for e in raw if isinstance(e, dict)]
        else:
            inner = raw.get("events", []) if isinstance(raw, dict) else []
            events = [e for e in inner if isinstance(e, dict)]
        log.info("[event_forwarder] Collected %d events", len(events))
        return events
    except Exception as exc:
        log.error("[event_forwarder] collect error: %s", exc)
        return []


def forward(session_id: str, events: List[Dict[str, Any]], api_key: str) -> int:
    if not api_key or not events:
        return 0
    batch = [
        {
            "tool_name":    e.get("tool_name", ""),
            "tool_args":    e.get("tool_args", {}),
            "tool_result":  e.get("tool_result"),
            "attack_run_id": e.get("attack_run_id"),
            "executed":     bool(e.get("executed", False)),
            "phase":        e.get("phase", ""),
            "timestamp":    e.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }
        for e in events
    ]
    log.info("[event_forwarder] Forwarding %d events for session=%s → %s/api/v1/events/batch",
             len(batch), session_id, CLOUD_API_URL)
    try:
        resp = requests.post(
            f"{CLOUD_API_URL}/api/v1/events/batch",
            json={"session_id": session_id, "events": batch},
            headers={"X-API-Key": api_key},
            timeout=15,
        )
        log.info("[event_forwarder] Forward complete: session=%s status=%d", session_id, resp.status_code)
        return resp.status_code
    except Exception as exc:
        log.error("[event_forwarder] forward error: %s", exc)
        return 0
