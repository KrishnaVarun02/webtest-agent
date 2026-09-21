from __future__ import annotations

from fastapi.testclient import TestClient

from webtest_agent_orchestrator.api import create_app
from webtest_agent_orchestrator.services import OrchestratorService


def test_exact_extension_review_and_generate_contract(settings, extension_payload, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    client = TestClient(create_app(settings, service))
    assert client.get("/health").json()["status"] == "ok"
    response = client.post("/api/v1/review", json=extension_payload)
    assert response.status_code == 200, response.text
    body = response.json()
    plan = body["plan"]
    assert plan["status"] == "draft"
    plan["approved"] = True
    generated = client.post(
        "/api/v1/generate",
        json={"recordingId": extension_payload["sessionId"], "approved": True, "approvedPlan": plan},
    )
    assert generated.status_code == 200, generated.text
    result = generated.json()
    assert result["status"] == "completed"
    assert result["projectPath"].endswith("webtest-generated-tests")
    assert result["reportPath"].endswith(".html")


def test_generate_rejects_unapproved_plan(settings, extension_payload, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    client = TestClient(create_app(settings, service))
    plan = client.post("/api/v1/review", json=extension_payload).json()["plan"]
    response = client.post(
        "/api/v1/generate",
        json={"recordingId": extension_payload["sessionId"], "approved": False, "approvedPlan": plan},
    )
    assert response.status_code == 409


def test_exact_extension_exploration_contract(settings, fake_generator) -> None:
    client = TestClient(create_app(settings, OrchestratorService(settings, generator=fake_generator)))
    response = client.post(
        "/api/v1/explore/next",
        json={
            "schemaVersion": "1.0.0",
            "snapshot": {
                "currentUrl": "https://app.example.test/login",
                "title": "Login",
                "headings": ["Login"],
                "interactiveElements": [{"ref": "username", "role": "textbox", "name": "Username", "enabled": True}],
                "visitedPageSummary": [],
                "observedApis": [],
            },
            "history": [],
            "observedApis": [],
            "availableTestDataRefs": ["TEST_USERNAME"],
            "limits": {"maxActions": 5, "maxRuntimeMs": 5000, "maxRetries": 2, "maxRepeatedStates": 2},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"type": "fill", "elementRef": "username", "valueRef": "TEST_USERNAME"}


def test_review_ui_and_cors(settings, fake_generator) -> None:
    client = TestClient(create_app(settings, OrchestratorService(settings, generator=fake_generator)))
    response = client.get("/review")
    assert response.status_code == 200
    assert "scenario review" in response.text
    response = client.options(
        "/api/v1/review",
        headers={"Origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers["access-control-allow-origin"].startswith("chrome-extension://")


def test_extension_schema_validation_is_strict(settings, extension_payload, fake_generator) -> None:
    extension_payload["unexpected"] = "not accepted"
    client = TestClient(create_app(settings, OrchestratorService(settings, generator=fake_generator)))
    response = client.post("/api/v1/review", json=extension_payload)
    assert response.status_code == 422

