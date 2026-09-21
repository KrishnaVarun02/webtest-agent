from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

from .exploration import ExplorationAgent
from .schemas import (
    CapturedRequest,
    ExplorationPolicy,
    ExplorationRequest,
    ExplorationSnapshot,
    ExtensionAiAction,
    ExtensionExplorationRequest,
    ExtensionHeader,
    ExtensionRecording,
    InteractiveElement,
    LocatorCandidate,
    Recording,
    UIAction,
)
from .security import url_origin


def _headers(values: list[ExtensionHeader], explicit_content_type: str | None = None) -> dict[str, Any]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for header in values:
        grouped[header.name].append(header.value)
    result: dict[str, Any] = {
        name: items[0] if len(items) == 1 else items
        for name, items in grouped.items()
    }
    if explicit_content_type and not any(name.lower() == "content-type" for name in result):
        result["Content-Type"] = explicit_content_type
    return result


def extension_recording_to_canonical(value: ExtensionRecording) -> Recording:
    strategy = {
        "test-attribute": "test_attribute",
        "role": "role_name",
        "label": "label",
        "id": "id",
        "css": "css",
    }
    actions: list[UIAction] = []
    for action in value.actions:
        locators = []
        if action.locator:
            locator_value = action.locator.value
            if action.locator.strategy == "role" and action.locator.name:
                locator_value = f"{action.locator.role or 'element'}:{action.locator.name}"
            locators.append(LocatorCandidate(strategy=strategy[action.locator.strategy], value=locator_value))
        actions.append(
            UIAction(
                id=action.id,
                type=action.type,
                timestamp=action.timestamp,
                page_url=action.page_url,
                locator_candidates=locators,
                value=action.value,
                metadata={**action.metadata, "sourceSessionId": action.session_id},
            )
        )

    requests: list[CapturedRequest] = []
    for operation in value.operations:
        query: dict[str, Any] = {}
        for item in operation.request.query:
            if item.name not in query:
                query[item.name] = item.value
            elif isinstance(query[item.name], list):
                query[item.name].append(item.value)
            else:
                query[item.name] = [query[item.name], item.value]
        requests.append(
            CapturedRequest(
                id=operation.id,
                session_id=operation.session_id,
                method=operation.request.method,
                url=operation.request.url,
                normalized_path=operation.request.normalized_path,
                query_parameters=query,
                request_headers=_headers(operation.request.headers, operation.request.content_type),
                request_content_type=operation.request.content_type,
                request_body=operation.request.body,
                response_status=operation.response.status,
                response_headers=_headers(operation.response.headers, operation.response.content_type),
                response_body=operation.response.body,
                page_url=operation.page_url,
                timestamp=operation.timestamp,
                timing=operation.timing,
                related_ui_action_id=operation.related_action_id,
                resource_type=operation.resource_type,
                excluded=not operation.included,
            )
        )
    page_url = next(
        (item.page_url for item in [*actions, *requests] if item.page_url),
        value.configuration.allowed_origins[0],
    )
    return Recording(
        schema_version="1.0",
        session_id=value.session_id,
        allowed_origins=value.configuration.allowed_origins,
        started_at=value.started_at,
        ended_at=value.ended_at,
        page_url=page_url,
        include_patterns=value.configuration.include_patterns,
        exclude_patterns=value.configuration.exclude_patterns,
        actions=actions,
        requests=requests,
        metadata={
            "product": value.product,
            "sourceSchemaVersion": value.schema_version,
            "inspectedTabId": value.inspected_tab_id,
            "maxOperations": value.configuration.max_operations,
            **value.metadata.model_dump(mode="json", by_alias=True),
        },
    )


def recording_from_wire(payload: dict[str, Any]) -> Recording:
    if payload.get("schemaVersion") == "1.0.0" or "operations" in payload:
        return extension_recording_to_canonical(ExtensionRecording.model_validate(payload))
    if set(payload) == {"recording"}:
        payload = payload["recording"]
    return Recording.model_validate(payload)


def _snapshot_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _best_ref(element_name: str, refs: list[str]) -> str | None:
    if not refs:
        return None
    words = set(re.findall(r"[a-z0-9]+", element_name.lower()))
    scored: list[tuple[int, str]] = []
    for ref in refs:
        ref_words = set(re.findall(r"[a-z0-9]+", ref.lower()))
        score = len(words & ref_words)
        if "password" in words and "password" in ref_words:
            score += 10
        if words & {"user", "username", "email"} and ref_words & {"user", "username", "email"}:
            score += 8
        scored.append((score, ref))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def extension_exploration_to_canonical(value: ExtensionExplorationRequest) -> tuple[ExplorationRequest, dict[str, str]]:
    ref_for_element: dict[str, str] = {}
    test_data: dict[str, str] = {}
    elements: list[InteractiveElement] = []
    state_change = re.compile(r"create|add|save|update|submit|send|publish|archive|delete|remove|confirm|approve|register|sign up", re.I)
    for element in value.snapshot.interactive_elements:
        data_ref = _best_ref(element.name, value.available_test_data_refs)
        if data_ref:
            ref_for_element[element.ref] = data_ref
            test_data[element.ref] = data_ref
            test_data[element.name] = data_ref
        elements.append(
            InteractiveElement(
                ref=element.ref,
                role=element.role,
                name=element.name,
                enabled=element.enabled,
                likely_state_changing=bool(state_change.search(f"{element.role} {element.name}")),
            )
        )
    snapshot_dump = value.snapshot.model_dump(mode="json", by_alias=True)
    canonical = ExplorationRequest(
        snapshot=ExplorationSnapshot(
            current_url=value.snapshot.current_url,
            page_title=value.snapshot.title,
            headings=value.snapshot.headings,
            elements=elements,
            visited_pages=[page.url for page in value.snapshot.visited_page_summary],
            observed_apis=[f"{api.method} {api.normalized_path} -> {api.status}" for api in value.observed_apis],
            state_fingerprint=_snapshot_hash(snapshot_dump),
        ),
        policy=ExplorationPolicy(
            allowed_origins=[url_origin(value.snapshot.current_url)],
            max_actions=value.limits.max_actions,
            max_runtime_seconds=max(1, value.limits.max_runtime_ms // 1000),
            actions_taken=len(value.history),
            attempted_element_refs=[action.element_ref for action in value.history if action.element_ref],
            max_retries_per_state=value.limits.max_retries,
            test_data=test_data,
        ),
    )
    return canonical, ref_for_element


def extension_action_from_canonical(action: Any, refs: dict[str, str]) -> dict[str, Any]:
    if action.action == "stop":
        return ExtensionAiAction(type="stop", reason=action.reason[:300]).model_dump(mode="json", by_alias=True, exclude_none=True)
    if action.action == "click":
        return ExtensionAiAction(type="click", element_ref=action.element_ref).model_dump(mode="json", by_alias=True, exclude_none=True)
    if action.action in {"fill", "select"}:
        value_ref = refs.get(action.element_ref or "")
        if not value_ref:
            return ExtensionAiAction(type="stop", reason="No approved local test-data reference is available").model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
        return ExtensionAiAction(type=action.action, element_ref=action.element_ref, value_ref=value_ref).model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
    if action.action == "navigate":
        return ExtensionAiAction(type="navigate", url=action.url).model_dump(mode="json", by_alias=True, exclude_none=True)
    if action.action == "back":
        return {"type": "back"}
    if action.action == "scroll":
        return {"type": "scroll", "direction": "down", "amount": 600}
    return {"type": "wait", "durationMs": 500}


def extension_next_action(payload: dict[str, Any], agent: ExplorationAgent) -> dict[str, Any]:
    extension_request = ExtensionExplorationRequest.model_validate(payload)
    canonical, refs = extension_exploration_to_canonical(extension_request)
    return extension_action_from_canonical(agent.next_action(canonical), refs)
