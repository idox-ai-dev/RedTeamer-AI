#!/usr/bin/env python3
"""OpenClaw Red Team — Cloud API Server"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_base_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
load_dotenv(_base_dir / '.env')

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
            _log_dir / "api-server.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger(__name__)

from database import init_db, SessionLocal
from models_db import Scenario

app = FastAPI(
    title="OpenClaw Red Team Cloud API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class _RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        log.info("→ %s %s", request.method, request.url.path)
        response = await call_next(request)
        log.info("← %s %s %d", request.method, request.url.path, response.status_code)
        return response

app.add_middleware(_RequestLogMiddleware)

# ── Routers ────────────────────────────────────────────────────────
from routers.clients     import router as clients_router
from routers.scenarios   import router as scenarios_router
from routers.attacks     import router as attacks_router
from routers.evaluations import router as evaluations_router
from routers.events      import router as events_router
from routers.jobs        import router as jobs_router

app.include_router(clients_router,     prefix="/api/v1")
app.include_router(scenarios_router,   prefix="/api/v1")
app.include_router(attacks_router,     prefix="/api/v1")
app.include_router(evaluations_router, prefix="/api/v1")
app.include_router(events_router,      prefix="/api/v1")
app.include_router(jobs_router,        prefix="/api/v1")

# ── Static (Web UI) ────────────────────────────────────────────────
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "OpenClaw Red Team Cloud API", "docs": "/api/docs", "ui": "/ui"}


@app.get("/api/v1/config", include_in_schema=False)
def get_config():
    return {
        "default_agent_url": os.environ.get("DEFAULT_AGENT_URL", ""),
    }


# ── Startup ────────────────────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()
    _migrate_add_job_id()
    _seed_builtin_scenarios()


def _migrate_add_job_id():
    """Add job_id column to attack_sessions if it doesn't exist (SQLite migration)."""
    from sqlalchemy import inspect, text
    from database import engine
    try:
        cols = [c["name"] for c in inspect(engine).get_columns("attack_sessions")]
        if "job_id" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE attack_sessions ADD COLUMN job_id VARCHAR REFERENCES test_jobs(id)"))
                conn.commit()
            log.info("Migrated: added job_id to attack_sessions")
    except Exception as e:
        log.warning("Migration job_id skipped: %s", e)


def _seed_builtin_scenarios():
    SCENARIOS_DIR = Path(__file__).parent / "scenarios"
    if not SCENARIOS_DIR.exists():
        return
    db = SessionLocal()
    try:
        existing = {s.scenario_key: s for s in db.query(Scenario).filter(Scenario.source == "builtin").all()}
        for yaml_file in sorted(SCENARIOS_DIR.glob("*.yaml")):
            try:
                with yaml_file.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                key = data.get("id", yaml_file.stem)
                input_json        = json.dumps(data.get("input", {}))
                expected_json     = json.dumps(data.get("expected", {"decision": "block"}))
                assertions        = json.dumps(data.get("assertions", []))
                owasp_json        = json.dumps(data.get("owasp_mapping", []))
                sc_type           = data.get("type", "agent_attack")
                evaluation_json   = json.dumps(data.get("evaluation", {}))
                if key in existing:
                    sc = existing[key]
                    sc.name              = data.get("name", key)
                    sc.input_json        = input_json
                    sc.expected_json     = expected_json
                    sc.assertions        = assertions
                    sc.owasp_json        = owasp_json
                    sc.type              = sc_type
                    sc.evaluation_json   = evaluation_json
                else:
                    sc = Scenario(
                        scenario_key=key,
                        name=data.get("name", key),
                        input_json=input_json,
                        expected_json=expected_json,
                        assertions=assertions,
                        owasp_json=owasp_json,
                        type=sc_type,
                        evaluation_json=evaluation_json,
                        source="builtin",
                        client_id=None,
                    )
                    db.add(sc)
            except Exception as e:
                log.warning("Failed to seed %s: %s", yaml_file, e)
        db.commit()
        log.info("Builtin scenarios synced from %s", SCENARIOS_DIR)
    finally:
        db.close()



if __name__ == "__main__":
    import uvicorn
    _reload = os.environ.get("UVICORN_RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run(
        "main:app",
        host=os.environ.get("API_HOST", "0.0.0.0"),
        port=int(os.environ.get("API_PORT", "8000")),
        reload=_reload,
    )
