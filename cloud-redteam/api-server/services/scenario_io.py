from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

GENERATED_DIR = Path(__file__).parent.parent / "scenarios" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)


def _block_str_representer(dumper, data):
    if '\n' in data:
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='>')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)


yaml.add_representer(str, _block_str_representer)


def save_scenario_yaml(scenario) -> Path:
    """Write a generated Scenario ORM object to scenarios/generated/<key>.yaml."""
    safe_key = re.sub(r"[^\w\-]", "_", scenario.scenario_key)
    path = GENERATED_DIR / f"{safe_key}.yaml"

    input_data    = json.loads(scenario.input_json)
    expected      = json.loads(scenario.expected_json)
    assertions    = json.loads(scenario.assertions)
    owasp         = json.loads(scenario.owasp_json)
    sc_type    = getattr(scenario, "type", "agent_attack")
    evaluation = json.loads(getattr(scenario, "evaluation_json", "{}"))

    doc = {
        "id":           scenario.scenario_key,
        "name":         scenario.name,
        "type":         sc_type,
        "owasp_mapping": owasp,
        "target":       {"adapter": "openclaw_cli"},
        "input":        input_data,
        "expected":     expected,
        "assertions":   assertions,
    }
    if evaluation:
        doc["evaluation"] = evaluation

    with path.open("w", encoding="utf-8") as f:
        yaml.dump(doc, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    return path
