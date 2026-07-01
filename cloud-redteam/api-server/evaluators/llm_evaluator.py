from __future__ import annotations

from typing import Any, Dict, List

from services.llm_service import evaluate_with_llm as _llm_eval


async def evaluate(scenario: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    return await _llm_eval(scenario, events)
