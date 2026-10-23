"""n8n_trigger: POST a JSON payload to a configured n8n webhook (confirm: external effects)."""
from __future__ import annotations

import json

from jarvis.core import config
from jarvis.core.registry import tool


def _post(url: str, payload: dict):
    import httpx  # lazy

    return httpx.post(url, json=payload, timeout=config.N8N_TIMEOUT_S)


@tool(group="automation", safety="confirm", description="Trigger an n8n workflow webhook with a JSON payload.")
def n8n_trigger(workflow: str, payload_json: str = "{}") -> str:
    """Trigger an n8n workflow.

    Args:
        workflow: Workflow name as configured in N8N_WEBHOOKS, e.g. "backup".
        payload_json: JSON object to send, e.g. '{"note": "hi"}'.
    """
    hooks = config.N8N_WEBHOOKS
    url = hooks.get((workflow or "").strip())
    if not url:
        names = ", ".join(sorted(hooks)) or "none configured (config.N8N_WEBHOOKS)"
        return f"error: unknown workflow {workflow!r}; available: {names}"
    try:
        payload = json.loads(payload_json or "{}")
    except ValueError as e:
        return f"error: payload_json is not valid JSON: {e}"
    if not isinstance(payload, dict):
        return "error: payload_json must be a JSON object"
    try:
        r = _post(url, payload)
    except Exception as e:
        return f"error: n8n request failed: {type(e).__name__}: {str(e)[:200]}"
    body = (r.text or "").strip().replace("\n", " ")[:300]
    status = "ok" if 200 <= r.status_code < 300 else "error"
    return f"{status}: n8n {workflow} returned HTTP {r.status_code}" + (f": {body}" if body else "")
