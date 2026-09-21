from __future__ import annotations

import json

import pytest

from webtest_agent_orchestrator.normalization import CaptureNormalizer, normalize_path
from webtest_agent_orchestrator.schemas import CapturedRequest
from webtest_agent_orchestrator.security import canonical_origin, is_sensitive_name, redact, redact_string, sanitize_url


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/users/123", "/api/users/{userId}"),
        ("/api/users/456", "/api/users/{userId}"),
        ("/v1/records/11111111-1111-4111-8111-111111111111", "/v1/records/{recordId}"),
        ("/reports/2026", "/reports/{reportId}"),
        ("/api/v2/status", "/api/v2/status"),
    ],
)
def test_path_normalization(path: str, expected: str) -> None:
    normalized, _ = normalize_path(path)
    assert normalized == expected


def test_origin_and_url_sanitization() -> None:
    assert canonical_origin("HTTPS://Example.test:443") == "https://example.test"
    assert "abc123" not in sanitize_url("https://example.test/a?token=abc123&safe=yes#fragment")
    with pytest.raises(ValueError):
        canonical_origin("https://example.test/path")


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "api_key",
        "refreshToken",
        "clientSecret",
        "passwordHash",
        "authorizationValue",
        "user-password",
        "session_id",
        "credential",
    ],
)
def test_sensitive_field_detection(name: str) -> None:
    assert is_sensitive_name(name)


def test_recursive_redaction_preserves_shape() -> None:
    value = redact(
        {
            "profile": {
                "password": "seeded-password",
                "clientSecret": "client-leak",
                "passwordHash": "hash-leak",
                "authorizationValue": "authorization-leak",
                "name": "safe",
            },
            "Authorization": "Bearer token-value",
        }
    )
    text = json.dumps(value)
    for secret in ("seeded-password", "client-leak", "hash-leak", "authorization-leak", "token-value"):
        assert secret not in text
    assert value["profile"]["name"] == "safe"
    assert value["profile"]["password"] == "${TEST_PASSWORD}"


def test_free_form_assignments_are_redacted_without_corrupting_references_or_jsonpaths() -> None:
    raw = "password=LEAK clientSecret:CLIENT-LEAK passwordHash=HASH-LEAK authorizationValue=AUTH-LEAK"
    safe = redact_string(raw)
    for secret in ("LEAK", "CLIENT-LEAK", "HASH-LEAK", "AUTH-LEAK"):
        assert secret not in safe
    assert redact_string("${TEST_PASSWORD}") == "${TEST_PASSWORD}"
    assert redact_string("password=${TEST_PASSWORD}") == "password=${TEST_PASSWORD}"
    assert redact_string("$.clientSecret") == "$.clientSecret"


def test_normalizer_deduplicates_correlates_and_removes_secrets(canonical_recording) -> None:
    # A second concrete ID must collapse into the same normalized GET operation,
    # while preserving a distinct useful payload example.
    duplicate = canonical_recording.requests[1].model_copy(
        update={
            "id": "get-two",
            "url": "https://app.example.test/api/users/22222222-2222-4222-8222-222222222222",
            "response_body": {"id": "22222222-2222-4222-8222-222222222222", "name": "Bob"},
        }
    )
    canonical_recording.requests.append(duplicate)
    canonical_recording.requests.append(
        CapturedRequest(
            id="analytics",
            method="POST",
            url="https://app.example.test/analytics/collect",
            response_status=204,
            timestamp=canonical_recording.started_at,
            resource_type="fetch",
        )
    )
    normalized = CaptureNormalizer().normalize(canonical_recording)
    assert len(normalized.operations) == 2
    get = next(operation for operation in normalized.operations if operation.method == "GET")
    assert get.normalized_path == "/api/users/{userId}"
    assert len(get.examples) == 2
    assert get.related_ui_action_ids == ["action-create"]
    assert normalized.filtered_request_count == 1
    serialized = normalized.model_dump_json()
    for secret in ("top-secret-token", "never-store-this", "session-secret", "query-secret"):
        assert secret not in serialized


def test_unauthorized_origin_is_never_normalized(canonical_recording) -> None:
    canonical_recording.requests.append(
        canonical_recording.requests[1].model_copy(
            update={"id": "foreign", "url": "https://tracker.invalid/api/users/123"}
        )
    )
    normalized = CaptureNormalizer().normalize(canonical_recording)
    assert all(operation.origin == "https://app.example.test" for operation in normalized.operations)
    assert any(item.reason == "origin is not authorized" for item in normalized.unsupported_traffic)
