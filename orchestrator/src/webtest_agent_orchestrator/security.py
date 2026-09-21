from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .schemas import Recording


REDACTED = "${REDACTED}"
SENSITIVE_FRAGMENTS = (
    "token",
    "key",
    "secret",
    "password",
    "passwd",
    "passphrase",
    "authorization",
    "credential",
    "cookie",
    "session",
)
AUTH_HEADER = re.compile(r"^(?:proxy-)?authorization$", re.IGNORECASE)
COOKIE_HEADER = re.compile(r"^(?:cookie|set-cookie)$", re.IGNORECASE)
BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{6,}")
BASIC = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{6,}")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
TEXTUAL_SECRET = re.compile(
    r"(?i)(\b[A-Za-z0-9_.-]*(?:token|key|secret|password|passwd|passphrase|authorization|credential|"
    r"cookie|session(?:[_-]?id)?)[A-Za-z0-9_.-]*\b\s*[:=]\s*)"
    r"(\$\{[A-Z][A-Z0-9_]*\}|\"[^\"]*\"|'[^']*'|[^\s,;}&\#]+)"
)
ENV_REFERENCE = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")


def is_sensitive_name(name: object) -> bool:
    text = str(name).strip()
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    return bool(
        any(fragment in compact for fragment in SENSITIVE_FRAGMENTS)
        or AUTH_HEADER.match(text)
        or COOKIE_HEADER.match(text)
    )


def secret_reference(name: object) -> str:
    lowered = str(name).lower()
    if "password" in lowered or "passwd" in lowered or "passphrase" in lowered:
        return "${TEST_PASSWORD}"
    if "cookie" in lowered or "session" in lowered:
        return "${SESSION_COOKIE}"
    if "username" in lowered or lowered.endswith("user"):
        return "${TEST_USERNAME}"
    if "credential" in lowered:
        return "${CREDENTIAL}"
    return "${API_TOKEN}"


def redact_string(value: str) -> str:
    if ENV_REFERENCE.fullmatch(value.strip()):
        return value.strip()
    result = BEARER.sub("Bearer ${API_TOKEN}", value)
    result = BASIC.sub("Basic ${BASIC_CREDENTIALS}", result)
    result = JWT.sub("${API_TOKEN}", result)
    result = TEXTUAL_SECRET.sub(_redact_textual_assignment, result)
    return result


def _redact_textual_assignment(match: re.Match[str]) -> str:
    raw_value = match.group(2)
    unquoted = raw_value[1:-1] if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in "\"'" else raw_value
    if ENV_REFERENCE.fullmatch(unquoted):
        return match.group(0)
    return match.group(1) + REDACTED


def redact(value: Any, *, key: object | None = None, max_string_bytes: int = 1_000_000) -> Any:
    """Return a JSON-compatible deep copy with secret-bearing values removed."""
    if key is not None and is_sensitive_name(key):
        return secret_reference(key)
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=k, max_string_bytes=max_string_bytes) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact(item, max_string_bytes=max_string_bytes) for item in value]
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) > max_string_bytes:
            value = encoded[:max_string_bytes].decode("utf-8", errors="ignore") + "...[TRUNCATED]"
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                pass
            else:
                return redact(decoded, max_string_bytes=max_string_bytes)
        return redact_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_string(str(value))


def redact_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    return {str(name): redact(value, key=name) for name, value in headers.items()}


def sanitize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return redact_string(url)
    hostname = parts.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    pairs = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        pairs.append((name, secret_reference(name) if is_sensitive_name(name) else redact_string(value)))
    return urlunsplit((parts.scheme.lower(), netloc.lower(), parts.path, urlencode(pairs, doseq=True), ""))


def canonical_origin(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"invalid origin: {value!r}") from exc
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"allowed origin must be an absolute HTTP(S) origin: {value!r}")
    if parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment:
        raise ValueError(f"allowed origin must not contain credentials, a path, query, or fragment: {value!r}")
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (parts.scheme.lower() == "http" and parts.port == 80) or (
        parts.scheme.lower() == "https" and parts.port == 443
    )
    port = "" if default_port or parts.port is None else f":{parts.port}"
    return f"{parts.scheme.lower()}://{host}{port}"


def url_origin(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        raise ValueError(f"request URL must be absolute HTTP(S): {value!r}")
    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (parts.scheme.lower() == "http" and parts.port == 80) or (
        parts.scheme.lower() == "https" and parts.port == 443
    )
    port = "" if default_port or parts.port is None else f":{parts.port}"
    return f"{parts.scheme.lower()}://{host}{port}"


def sanitize_recording(recording: Recording, *, max_payload_bytes: int = 1_000_000) -> Recording:
    clone = deepcopy(recording)
    clone.allowed_origins = [canonical_origin(origin) for origin in clone.allowed_origins]
    clone.page_url = sanitize_url(clone.page_url) if clone.page_url else ""
    for action in clone.actions:
        action.page_url = sanitize_url(action.page_url) if action.page_url else ""
        metadata_text = " ".join(str(item) for item in action.metadata.values())
        if action.value is not None:
            if any(is_sensitive_name(key) for key in action.metadata) or is_sensitive_name(metadata_text):
                action.value = secret_reference(metadata_text)
            else:
                action.value = redact(action.value, max_string_bytes=max_payload_bytes)
        action.metadata = redact(action.metadata, max_string_bytes=max_payload_bytes)
    for request in clone.requests:
        request.url = sanitize_url(request.url)
        request.page_url = sanitize_url(request.page_url) if request.page_url else ""
        request.query_parameters = redact(request.query_parameters, max_string_bytes=max_payload_bytes)
        request.request_headers = redact_headers(request.request_headers)
        request.response_headers = redact_headers(request.response_headers)
        request.request_body = redact(request.request_body, max_string_bytes=max_payload_bytes)
        request.response_body = redact(request.response_body, max_string_bytes=max_payload_bytes)
    clone.metadata = redact(clone.metadata, max_string_bytes=max_payload_bytes)
    return clone


def sanitized_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(redact(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def contains_forbidden_literal(value: Any, literal: str) -> bool:
    if not literal:
        return False
    serialized = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return literal in serialized


def redact_known_secrets(text: str, extra_literals: list[str] | None = None) -> str:
    """Redact credential-like environment values and caller-known literals."""
    literals = list(extra_literals or [])
    for name, value in os.environ.items():
        if value and len(value) >= 4 and is_sensitive_name(name):
            literals.append(value)
    result = redact_string(text)
    for literal in sorted(set(literals), key=len, reverse=True):
        if literal:
            result = result.replace(literal, REDACTED)
    return result
