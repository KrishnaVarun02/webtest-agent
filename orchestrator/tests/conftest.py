from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from webtest_agent_orchestrator.config import Settings
from webtest_agent_orchestrator.schemas import CapturedRequest, Recording, UIAction


@pytest.fixture
def extension_payload() -> dict[str, Any]:
    fixture = Path(__file__).resolve().parents[2] / "scripts" / "fixtures" / "sample-recording.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "data" / "orchestrator.db",
        generated_root=tmp_path / "generated",
        report_root=tmp_path / "reports",
        generator_root=tmp_path / "absent-generator",
    )


@pytest.fixture
def canonical_recording() -> Recording:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Recording(
        session_id="session-fixture",
        allowed_origins=["https://app.example.test"],
        started_at=start,
        page_url="https://app.example.test/records",
        actions=[
            UIAction(
                id="action-create",
                type="click",
                timestamp=start,
                page_url="https://app.example.test/records",
            )
        ],
        requests=[
            CapturedRequest(
                id="create",
                session_id="session-fixture",
                method="POST",
                url="https://app.example.test/api/users",
                request_headers={"Content-Type": "application/json", "Authorization": "Bearer top-secret-token"},
                request_content_type="application/json",
                request_body={"name": "Alice", "password": "never-store-this"},
                response_status=201,
                response_headers={"Content-Type": "application/json", "Set-Cookie": "sid=session-secret"},
                response_body={"id": "11111111-1111-4111-8111-111111111111", "name": "Alice"},
                page_url="https://app.example.test/records",
                timestamp=start,
                related_ui_action_id="action-create",
            ),
            CapturedRequest(
                id="get-one",
                session_id="session-fixture",
                method="GET",
                url="https://app.example.test/api/users/11111111-1111-4111-8111-111111111111?api_key=query-secret",
                request_headers={"Authorization": "Bearer top-secret-token"},
                response_status=200,
                response_headers={"Content-Type": "application/json"},
                response_body={"id": "11111111-1111-4111-8111-111111111111", "name": "Alice"},
                page_url="https://app.example.test/records",
                timestamp=start + timedelta(seconds=1),
            ),
        ],
    )


class FakeGenerator:
    name = "fake-generator"

    def __init__(self) -> None:
        self.plans: list[dict[str, Any]] = []

    def generate(self, plan: Any, output_root: Path, project_name: str) -> dict[str, Any]:
        self.plans.append(plan.model_dump(mode="json", by_alias=True))
        project = output_root / project_name
        project.mkdir(parents=True, exist_ok=True)
        file = project / "README.md"
        file.write_text("generated", encoding="utf-8")
        return {
            "projectPath": str(project),
            "generatedFiles": ["README.md"],
            "generator": self.name,
        }


@pytest.fixture
def fake_generator() -> FakeGenerator:
    return FakeGenerator()
