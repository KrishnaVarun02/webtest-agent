from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Iterable
from urllib.parse import unquote, urlsplit

from .schemas import (
    ActionCorrelation,
    CapturedRequest,
    NormalizedOperation,
    NormalizedRecording,
    OperationExample,
    ParameterEvidence,
    Recording,
    UnsupportedTraffic,
)
from .security import canonical_origin, sanitize_recording, sanitize_url, url_origin


STATIC_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".css",
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".map",
    ".mp3",
    ".mp4",
    ".ogg",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
}
STATIC_RESOURCE_TYPES = {"font", "image", "imageset", "media", "script", "stylesheet"}
SUPPORTED_RESOURCE_TYPES = {"fetch", "xhr", "xmlhttprequest", "other"}
ANALYTICS_MARKERS = {
    "analytics",
    "telemetry",
    "tracking",
    "doubleclick",
    "google-analytics",
    "googletagmanager",
    "segment.io",
    "mixpanel",
    "amplitude",
    "sentry.io",
    "/collect",
    "/metrics",
    "/beacon",
}
JSON_TYPES = {"application/json", "application/problem+json", "application/ld+json"}
FORM_TYPES = {"application/x-www-form-urlencoded"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
HEX_ID_RE = re.compile(r"^[0-9a-f]{16,64}$", re.I)
INTEGER_RE = re.compile(r"^[1-9][0-9]{0,18}$")
VERSION_RE = re.compile(r"^v[0-9]+(?:\.[0-9]+)?$", re.I)


def _singular(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", value).strip()
    words = cleaned.split()
    word = words[-1] if words else "resource"
    if word.lower().endswith("ies") and len(word) > 3:
        word = word[:-3] + "y"
    elif word.lower().endswith("sses"):
        word = word[:-2]
    elif word.lower().endswith("s") and not word.lower().endswith("ss"):
        word = word[:-1]
    word = word[:1].lower() + word[1:]
    return word or "resource"


def _parameter_name(previous_segment: str, used: set[str]) -> str:
    base = f"{_singular(previous_segment)}Id"
    name = base
    index = 2
    while name in used:
        name = f"{base}{index}"
        index += 1
    used.add(name)
    return name


def _dynamic_kind(segment: str, previous: str) -> str | None:
    if VERSION_RE.fullmatch(segment) or previous.lower() in {"v", "version"}:
        return None
    if UUID_RE.fullmatch(segment):
        return "uuid"
    if HEX_ID_RE.fullmatch(segment):
        return "hex"
    if INTEGER_RE.fullmatch(segment):
        return "integer"
    return None


def normalize_path(path: str) -> tuple[str, list[ParameterEvidence]]:
    """Normalize evidence-backed UUID, integer, and opaque hex path identifiers."""
    decoded = unquote(path or "/")
    segments = [segment for segment in decoded.split("/") if segment]
    normalized: list[str] = []
    evidence: list[ParameterEvidence] = []
    used: set[str] = set()
    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index else "resource"
        kind = _dynamic_kind(segment, previous)
        if kind:
            name = _parameter_name(previous, used)
            normalized.append("{" + name + "}")
            evidence.append(
                ParameterEvidence(
                    name=name,
                    samples=[segment],
                    value_type=kind,
                    evidence=f"Observed a {kind} value in path segment {index + 1}",
                )
            )
        else:
            normalized.append(segment)
    result = "/" + "/".join(normalized)
    if decoded.endswith("/") and result != "/":
        result += "/"
    return result or "/", evidence


def _resource_pattern(normalized_path: str) -> str:
    parts = [part for part in normalized_path.strip("/").split("/") if part]
    while parts and (parts[-1].startswith("{") or parts[-1].lower() in {"status", "result", "poll"}):
        parts.pop()
    if parts and parts[-1].lower() in {"api", "v1", "v2", "v3"}:
        return "/" + "/".join(parts)
    return "/" + "/".join(parts) if parts else "/"


def _content_type(headers: dict[str, Any], explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.split(";", 1)[0].strip().lower()
    for name, value in headers.items():
        if str(name).lower() == "content-type":
            return str(value).split(";", 1)[0].strip().lower()
    return None


def _schema_of(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {str(key): _schema_of(item) for key, item in sorted(value.items())},
            "observedRequired": sorted(str(key) for key in value),
        }
    if isinstance(value, list):
        schemas = [_schema_of(item) for item in value[:10]]
        first = schemas[0] if schemas else {}
        return {"type": "array", "items": first}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": "null"}
    text = str(value)
    if UUID_RE.fullmatch(text):
        return {"type": "string", "format": "uuid"}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[^\s]+", text):
        return {"type": "string", "format": "date-time"}
    return {"type": "string"}


def _merge_schema(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if not left:
        return right
    if left.get("type") != right.get("type"):
        return {"oneOf": [left, right]}
    if left.get("type") == "object":
        left_props = dict(left.get("properties", {}))
        right_props = dict(right.get("properties", {}))
        for key, schema in right_props.items():
            left_props[key] = _merge_schema(left_props.get(key, {}), schema)
        observed = sorted(set(left.get("observedRequired", [])) & set(right.get("observedRequired", [])))
        return {"type": "object", "properties": left_props, "observedRequired": observed}
    return left


def _matches_any(value: str, patterns: Iterable[str]) -> bool:
    return any(
        fnmatch.fnmatch(value, pattern) if any(marker in pattern for marker in "*?[") else pattern in value
        for pattern in patterns
    )


def _filter_reason(request: CapturedRequest, allowed_origins: set[str], include: list[str], exclude: list[str]) -> str | None:
    try:
        origin = url_origin(request.url)
    except ValueError:
        return "invalid or non-HTTP URL"
    if origin not in allowed_origins:
        return "origin is not authorized"
    lowered_url = request.url.lower()
    if request.excluded:
        return "excluded by the user"
    if include and not _matches_any(request.url, include):
        return "does not match an include pattern"
    if exclude and _matches_any(request.url, exclude):
        return "matches an exclude pattern"
    resource_type = request.resource_type.lower()
    if resource_type in STATIC_RESOURCE_TYPES or PurePosixPath(urlsplit(request.url).path).suffix.lower() in STATIC_EXTENSIONS:
        return "static resource"
    if any(marker in lowered_url for marker in ANALYTICS_MARKERS):
        return "analytics or telemetry traffic"
    if resource_type not in SUPPORTED_RESOURCE_TYPES:
        return f"unsupported resource type: {resource_type}"
    request_type = _content_type(request.request_headers, request.request_content_type)
    if request.request_body is not None and request_type and request_type not in JSON_TYPES | FORM_TYPES:
        if not request_type.endswith("+json"):
            return f"unsupported request content type: {request_type}"
    return None


def _closest_action_id(request: CapturedRequest, actions: list[Any]) -> str | None:
    action_ids = {action.id for action in actions}
    if request.related_ui_action_id in action_ids:
        return request.related_ui_action_id
    eligible = [action for action in actions if action.timestamp <= request.timestamp]
    if not eligible:
        return None
    return max(eligible, key=lambda action: action.timestamp).id


def _example_fingerprint(example: OperationExample) -> str:
    value = {
        "query": example.query_parameters,
        "request": example.request_body,
        "status": example.response_status,
        "response": example.response_body,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class CaptureNormalizer:
    def __init__(self, *, max_requests: int = 10_000, max_examples_per_operation: int = 5, max_payload_bytes: int = 1_000_000):
        self.max_requests = max_requests
        self.max_examples_per_operation = max_examples_per_operation
        self.max_payload_bytes = max_payload_bytes

    def normalize(self, recording: Recording) -> NormalizedRecording:
        if len(recording.requests) > self.max_requests:
            raise ValueError(f"recording contains more than {self.max_requests} requests")
        sanitized = sanitize_recording(recording, max_payload_bytes=self.max_payload_bytes)
        allowed_origins = {canonical_origin(origin) for origin in sanitized.allowed_origins}
        actions = sorted(sanitized.actions, key=lambda action: action.timestamp)
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        unsupported: list[UnsupportedTraffic] = []
        filtered = 0

        for request in sorted(sanitized.requests, key=lambda item: item.timestamp):
            reason = _filter_reason(request, allowed_origins, sanitized.include_patterns, sanitized.exclude_patterns)
            if reason:
                filtered += 1
                unsupported.append(
                    UnsupportedTraffic(
                        request_id=request.id,
                        method=request.method,
                        sanitized_url=sanitize_url(request.url),
                        reason=reason,
                    )
                )
                continue
            parts = urlsplit(request.url)
            origin = url_origin(request.url)
            normalized_path, parameters = normalize_path(parts.path)
            key = (request.method, origin, normalized_path)
            action_id = _closest_action_id(request, actions)
            example = OperationExample(
                request_id=request.id,
                timestamp=request.timestamp,
                url=sanitize_url(request.url),
                query_parameters=request.query_parameters,
                request_headers=request.request_headers,
                request_content_type=_content_type(request.request_headers, request.request_content_type),
                request_body=request.request_body,
                response_status=request.response_status,
                response_headers=request.response_headers,
                response_body=request.response_body,
                related_ui_action_id=action_id,
                page_url=request.page_url,
            )
            if key not in groups:
                groups[key] = {
                    "parameters": {},
                    "examples": [],
                    "fingerprints": set(),
                    "statuses": set(),
                    "request_types": set(),
                    "response_types": set(),
                    "actions": set(),
                    "auth": False,
                    "schema": {},
                    "count": 0,
                }
            group = groups[key]
            group["count"] += 1
            for parameter in parameters:
                current = group["parameters"].setdefault(parameter.name, parameter.model_dump())
                current["samples"] = list(dict.fromkeys(current["samples"] + parameter.samples))[:10]
            fingerprint = _example_fingerprint(example)
            if fingerprint not in group["fingerprints"] and len(group["examples"]) < self.max_examples_per_operation:
                group["fingerprints"].add(fingerprint)
                group["examples"].append(example)
            if request.response_status is not None:
                group["statuses"].add(request.response_status)
            request_type = _content_type(request.request_headers, request.request_content_type)
            response_type = _content_type(request.response_headers)
            if request_type:
                group["request_types"].add(request_type)
            if response_type:
                group["response_types"].add(response_type)
            if action_id:
                group["actions"].add(action_id)
            header_names = {str(name).lower() for name in request.request_headers}
            group["auth"] = group["auth"] or bool(
                header_names & {"authorization", "cookie", "x-api-key", "api-key"}
            )
            if request.response_body is not None and request.response_status and 200 <= request.response_status < 300:
                group["schema"] = _merge_schema(group["schema"], _schema_of(request.response_body))

        operations: list[NormalizedOperation] = []
        for method, origin, path in sorted(groups):
            group = groups[(method, origin, path)]
            identity = f"{method} {origin}{path}"
            operation_id = "op-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            async_evidence = (
                202 in group["statuses"]
                or path.lower().endswith(("/status", "/result", "/poll"))
                or (method == "GET" and group["count"] > 1 and any(part in path.lower() for part in ("job", "task", "operation")))
            )
            operations.append(
                NormalizedOperation(
                    operation_id=operation_id,
                    method=method,
                    origin=origin,
                    normalized_path=path,
                    resource_pattern=_resource_pattern(path),
                    path_parameters=[ParameterEvidence.model_validate(value) for value in group["parameters"].values()],
                    examples=group["examples"],
                    observed_statuses=sorted(group["statuses"]),
                    request_content_types=sorted(group["request_types"]),
                    response_content_types=sorted(group["response_types"]),
                    related_ui_action_ids=sorted(group["actions"]),
                    auth_evidence=group["auth"],
                    state_changing=method in {"POST", "PUT", "PATCH", "DELETE"},
                    asynchronous_evidence=async_evidence,
                    response_schema=group["schema"],
                )
            )

        correlation_map: dict[str, list[str]] = defaultdict(list)
        for operation in operations:
            for action_id in operation.related_ui_action_ids:
                correlation_map[action_id].append(operation.operation_id)
        correlations = [
            ActionCorrelation(action_id=action.id, operation_ids=sorted(correlation_map.get(action.id, [])))
            for action in actions
        ]
        pages = sorted(
            {
                page
                for page in [sanitized.page_url, *(action.page_url for action in actions), *(r.page_url for r in sanitized.requests)]
                if page
            }
        )
        stable_payload = {
            "session": sanitized.session_id,
            "origins": sorted(allowed_origins),
            "operations": [operation.model_dump(mode="json") for operation in operations],
        }
        recording_id = "rec-" + hashlib.sha256(
            json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:20]
        return NormalizedRecording(
            recording_id=recording_id,
            session_id=sanitized.session_id,
            allowed_origins=sorted(allowed_origins),
            operations=operations,
            actions=actions,
            correlations=correlations,
            pages_visited=pages,
            filtered_request_count=filtered,
            unsupported_traffic=unsupported,
        )
