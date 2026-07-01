from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth import get_current_client
from database import get_db
from models_db import Client, Scenario
from schemas import ScenarioCreate, ScenarioGenerateRequest, ScenarioOut
from services.llm_service import generate_scenarios_with_llm

router = APIRouter(prefix="/scenarios", tags=["scenarios"])
log = logging.getLogger(__name__)


def _to_dict(sc: Scenario) -> dict:
    return {
        "id":           sc.id,
        "scenario_key": sc.scenario_key,
        "name":         sc.name,
        "input":        json.loads(sc.input_json),
        "expected":     json.loads(sc.expected_json),
        "assertions":   json.loads(sc.assertions),
        "owasp_mapping": json.loads(sc.owasp_json),
        "source":       sc.source,
        "client_id":    sc.client_id,
        "created_at":   sc.created_at.isoformat(),
    }


@router.get("/", response_model=List[ScenarioOut])
def list_scenarios(
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    builtin  = db.query(Scenario).filter(Scenario.source == "builtin").all()
    mine     = db.query(Scenario).filter(
        Scenario.source == "generated", Scenario.client_id == current.id
    ).all()
    return builtin + mine


@router.post("/", response_model=ScenarioOut)
def create_scenario(
    body: ScenarioCreate,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    sc = Scenario(
        scenario_key=body.scenario_key,
        name=body.name,
        type=body.type,
        input_json=body.input_json,
        expected_json=body.expected_json,
        assertions=body.assertions,
        owasp_json=body.owasp_json,
        evaluation_json=body.evaluation_json,
        source="generated",
        client_id=current.id,
    )
    db.add(sc)
    db.commit()
    db.refresh(sc)
    log.info("Scenario created: key=%s client=%s", sc.scenario_key, current.name)
    try:
        from services.scenario_io import save_scenario_yaml
        save_scenario_yaml(sc)
    except Exception as e:
        log.warning("Failed to save YAML for %s: %s", sc.scenario_key, e)
    return sc


@router.post("/generate", response_model=List[ScenarioOut])
async def generate_scenarios(
    body: ScenarioGenerateRequest,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    log.info("Generating %d scenario(s) via LLM: query=%s", body.count, body.query[:80])
    generated = await generate_scenarios_with_llm(body.query, body.count)
    log.info("LLM returned %d scenario(s)", len(generated))
    saved = []
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    for g in generated:
        owasp_list = g.get("owasp_mapping", [])
        owasp_code = ""
        if owasp_list:
            m = re.search(r"(LLM\d+|ASI\d+)", owasp_list[0], re.IGNORECASE)
            if m:
                owasp_code = f"-{m.group(1).upper()}"
        suffix = uuid.uuid4().hex[:6].upper()
        unique_key = f"GEN-{ts}{owasp_code}-{suffix}"
        sc = Scenario(
            scenario_key=unique_key,
            name=g.get("name", "Generated Scenario"),
            input_json=json.dumps(g.get("input", {})),
            expected_json=json.dumps(g.get("expected", {"decision": "block"})),
            assertions=json.dumps(g.get("assertions", ["tool_call_captured"])),
            owasp_json=json.dumps(g.get("owasp_mapping", [])),
            evaluation_json=json.dumps(g.get("evaluation", {})),
            source="generated",
            client_id=current.id,
        )
        db.add(sc)
        saved.append(sc)
    db.commit()
    for s in saved:
        db.refresh(s)
        try:
            from services.scenario_io import save_scenario_yaml
            save_scenario_yaml(s)
        except Exception as e:
            log.warning("Failed to save YAML for %s: %s", s.scenario_key, e)
    log.info("Scenarios saved: %s", [s.scenario_key for s in saved])
    return saved


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    sc = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found")
    if sc.source == "generated" and sc.client_id != current.id:
        raise HTTPException(status_code=403, detail="Not your scenario")
    return sc


@router.delete("/{scenario_id}")
def delete_scenario(
    scenario_id: str,
    db: Session = Depends(get_db),
    current: Client = Depends(get_current_client),
):
    sc = db.query(Scenario).filter(
        Scenario.id == scenario_id,
        Scenario.client_id == current.id,
    ).first()
    if not sc:
        raise HTTPException(status_code=404, detail="Scenario not found or not yours")
    log.info("Scenario deleted: key=%s client=%s", sc.scenario_key, current.name)
    db.delete(sc)
    db.commit()
    return {"ok": True}
