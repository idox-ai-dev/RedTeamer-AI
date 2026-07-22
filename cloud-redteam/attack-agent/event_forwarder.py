from __future__ import annotations

import logging
import os
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

OBSERVER_URL  = os.environ.get("OBSERVER_URL", "http://127.0.0.1:18790")
CLOUD_API_URL = os.environ.get("CLOUD_API_URL", "http://localhost:8000")

log = logging.getLogger(__name__)

# Known openclaw startup config files — never relevant to security evaluation.
_STARTUP_CONFIG_FILES = frozenset({
    "USER.md", "MEMORY.md", "CLAUDE.md", "CLAUDE.local.md",
    "settings.json", "settings.local.json",
})


def clear_events() -> None:
    try:
        requests.delete(f"{OBSERVER_URL}/events", timeout=5)
    except Exception:
        pass


def start_run(run_id: str, oc_session: str) -> None:
    log.info("[event_forwarder] Starting run: %s (oc_session=%s)", run_id, oc_session)
    try:
        requests.post(
            f"{OBSERVER_URL}/run/start",
            json={"run_id": run_id, "oc_session": oc_session},
            timeout=5,
        )
        log.info("[event_forwarder] Run started: %s", run_id)
    except Exception as exc:
        log.error("[event_forwarder] start_run error: %s", exc)


def end_run(oc_session: str) -> None:
    try:
        requests.post(f"{OBSERVER_URL}/run/end", json={"oc_session": oc_session}, timeout=5)
        log.info("[event_forwarder] Run ended: oc_session=%s", oc_session)
    except Exception:
        pass


def collect(since_iso: str, run_id: Optional[str] = None, oc_session: Optional[str] = None) -> List[Dict[str, Any]]:
    log.info("[event_forwarder] Collecting events from %s since=%s oc_session=%s", OBSERVER_URL, since_iso, oc_session)
    try:
        # Use params dict so requests URL-encodes '+00:00' → '%2B00%3A00'.
        # Manual string interpolation leaves '+' unencoded, which the server's
        # url.searchParams.get() interprets as a space → NaN timestamp → no filtering.
        r = requests.get(f"{OBSERVER_URL}/events", params={"since": since_iso}, timeout=8)
        if not r.ok:
            log.warning("[event_forwarder] Collect returned HTTP %d", r.status_code)
            return []
        raw = r.json()
        if isinstance(raw, list):
            events = [e for e in raw if isinstance(e, dict)]
        else:
            inner = raw.get("events", []) if isinstance(raw, dict) else []
            events = [e for e in inner if isinstance(e, dict)]

        if oc_session:
            # Build openclaw run_id → oc_session map from events that carry both.
            # tool-call events have session_id=null in the hook payload so they are
            # attributed via this map instead of directly.
            run_id_to_session: dict[str, str] = {}
            for e in events:
                if e.get("run_id") and e.get("session_id"):
                    run_id_to_session[e["run_id"]] = e["session_id"]

            filtered = []
            for e in events:
                sid = e.get("session_id") or run_id_to_session.get(e.get("run_id", ""))
                if sid == oc_session:
                    filtered.append({**e, "session_id": sid})
            events = filtered

        log.info("[event_forwarder] Collected %d events", len(events))
        return events
    except Exception as exc:
        log.error("[event_forwarder] collect error: %s", exc)
        return []


def filter_for_evaluation(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove openclaw startup/config reads that are never relevant to security evaluation."""
    filtered = []
    for e in events:
        if e.get("tool_name") == "read":
            path = str(
                e.get("tool_args", {}).get("file_path", "")
                or e.get("tool_args", {}).get("path", "")
            )
            if pathlib.Path(path).name in _STARTUP_CONFIG_FILES:
                continue
        filtered.append(e)
    return filtered


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
