from __future__ import annotations

import json
import os
from typing import Any, Protocol

from .schemas import ExplorationAction, ExplorationRequest
from .security import redact


class StructuredProvider(Protocol):
    name: str
    available: bool

    def complete_json(self, *, system: str, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any] | None: ...


class OfflineProvider:
    name = "offline-deterministic"
    available = False

    def complete_json(self, *, system: str, payload: dict[str, Any], schema: dict[str, Any]) -> None:
        return None


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str):
        self.model = model
        self.available = bool(os.getenv("OPENAI_API_KEY"))
        self._client: Any | None = None
        if self.available:
            try:
                from openai import OpenAI
            except ImportError:
                self.available = False
            else:
                self._client = OpenAI()

    def complete_json(self, *, system: str, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available or self._client is None:
            return None
        # The payload is sanitized again at the final model boundary. API keys are
        # read by the SDK from the environment and are never part of this data.
        safe_payload = redact(payload)
        response = self._client.responses.create(
            model=self.model,
            instructions=system,
            input=json.dumps(safe_payload, sort_keys=True, ensure_ascii=False),
            store=False,
            max_output_tokens=300,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "webtest_action",
                    "strict": True,
                    "schema": schema,
                }
            },
        )
        output = getattr(response, "output_text", "")
        if not output:
            return None
        parsed = json.loads(output)
        return parsed if isinstance(parsed, dict) else None


def configured_provider(provider_name: str, model: str) -> StructuredProvider:
    if provider_name == "openai":
        return OpenAIProvider(model)
    return OfflineProvider()


EXPLORATION_SYSTEM = """You are a bounded test user for an explicitly authorized web application.
Return exactly one structured action. Select only a supplied element reference. Never emit JavaScript.
Do not attempt CAPTCHA solving, payments, purchases, account deletion, file uploads, privilege escalation,
authentication bypass, unrelated-domain navigation, or other unsafe actions. Prefer useful unvisited,
enabled elements. Stop when no useful safe path remains."""


EXPLORATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "action": {"enum": ["click", "fill", "select", "scroll", "wait", "back", "navigate", "stop"]},
        "elementRef": {"type": ["string", "null"]},
        "value": {"type": ["string", "null"]},
        "url": {"type": ["string", "null"]},
        "requiresApproval": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["action", "elementRef", "value", "url", "requiresApproval", "reason"],
}


def provider_exploration_action(provider: StructuredProvider, request: ExplorationRequest) -> ExplorationAction | None:
    if not provider.available:
        return None
    payload = {
        "snapshot": request.snapshot.model_dump(mode="json", by_alias=True),
        "limits": {
            "actionsTaken": request.policy.actions_taken,
            "maxActions": request.policy.max_actions,
            "elapsedSeconds": request.policy.elapsed_seconds,
            "maxRuntimeSeconds": request.policy.max_runtime_seconds,
            "attemptedElementRefs": request.policy.attempted_element_refs,
        },
        # Only names/references, never the actual user-supplied values.
        "availableTestDataRefs": sorted(set(request.policy.test_data)),
    }
    try:
        # Sanitize before crossing the provider interface; providers other than
        # the built-in OpenAI adapter must receive the same privacy boundary.
        result = provider.complete_json(system=EXPLORATION_SYSTEM, payload=redact(payload), schema=EXPLORATION_SCHEMA)
        return ExplorationAction.model_validate(result) if result else None
    except Exception:
        # Provider outages or malformed output must never disable manual capture
        # or deterministic exploration.
        return None
