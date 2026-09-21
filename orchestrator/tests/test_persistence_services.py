from __future__ import annotations

import json
from pathlib import Path

import pytest

from webtest_agent_orchestrator.adapters import recording_from_wire
from webtest_agent_orchestrator.persistence import SQLiteRepository
from webtest_agent_orchestrator.schemas import ApprovalRequest, PlanPatch
from webtest_agent_orchestrator.services import ApprovalRequiredError, OrchestratorService, poll_until


def test_graph_state_is_persisted_and_secret_free(settings, canonical_recording, fake_generator) -> None:
    repository = SQLiteRepository(settings.db_path)
    service = OrchestratorService(settings, repository=repository, generator=fake_generator)
    outcome = service.create_review(canonical_recording)
    assert outcome.run.status == "awaiting_review"
    assert service.get_run(outcome.run.run_id).current_node == "human_review"
    raw = repository.raw_database_text()
    for secret in ("top-secret-token", "never-store-this", "session-secret", "query-secret"):
        assert secret not in raw


def test_contained_sensitive_names_and_raw_assignments_never_persist(settings, canonical_recording, fake_generator) -> None:
    secrets = {
        "clientSecret": "PERSIST-CLIENT-LEAK",
        "passwordHash": "PERSIST-HASH-LEAK",
        "authorizationValue": "PERSIST-AUTH-LEAK",
    }
    canonical_recording.requests[0].request_body = {
        **secrets,
        "diagnostic": "password=PERSIST-RAW-LEAK",
    }
    service = OrchestratorService(settings, generator=fake_generator)
    service.create_review(canonical_recording)
    raw = service.repository.raw_database_text()
    for secret in (*secrets.values(), "PERSIST-RAW-LEAK"):
        assert secret not in raw


def test_edit_revision_approval_and_generation(settings, canonical_recording, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    outcome = service.create_review(canonical_recording)
    patch = PlanPatch(assumptions=[*outcome.plan.assumptions, "Reviewed locally"])
    edited = service.edit_plan(outcome.plan.plan_id, patch, revision=1)
    assert edited.revision == 2 and edited.status == "draft"
    with pytest.raises(ValueError, match="revision conflict"):
        service.edit_plan(outcome.plan.plan_id, patch, revision=1)
    with pytest.raises(ApprovalRequiredError):
        service.generate(
            outcome.normalized.recording_id,
            edited,
            project_name="tests",
            explicit_approval=False,
            validate_project=False,
        )
    approved = service.approve_plan(edited.plan_id, ApprovalRequest())
    result = service.generate(
        outcome.normalized.recording_id,
        approved,
        project_name="tests",
        explicit_approval=False,
        validate_project=False,
    )
    assert Path(result.project_path, "README.md").is_file()
    assert result.report_id
    report, html_path = service.repository.get_report(result.report_id)
    assert report.generated_files == ["README.md"]
    assert html_path and Path(html_path).is_file()
    assert service.get_run(result.generation_id).status == "completed"


def test_extension_session_id_can_resolve_recording(settings, extension_payload, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    outcome = service.create_review(recording_from_wire(extension_payload))
    result = service.generate(
        extension_payload["sessionId"],
        outcome.plan,
        project_name="fixture-tests",
        explicit_approval=True,
        validate_project=False,
    )
    assert result.generator == "fake-generator"


def test_persisted_approval_preserves_token_extractor_path_without_secret(settings, extension_payload, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    outcome = service.create_review(recording_from_wire(extension_payload))
    seeded_secret = "must-not-survive-plan-persistence"
    plan_with_test_data = outcome.plan.model_copy(
        update={"supplied_test_data": {"API_TOKEN": seeded_secret}}
    )
    service.repository.save_plan(plan_with_test_data)
    approved = service.approve_plan(outcome.plan.plan_id, ApprovalRequest())
    login = next(
        step
        for workflow in approved.workflows
        for step in workflow.steps
        if "login" in step.name.lower()
    )
    assert login.extracts["api_token"] == "$.accessToken"
    assert approved.supplied_test_data["API_TOKEN"] == "${API_TOKEN}"
    assert seeded_secret not in service.repository.raw_database_text()


def test_poll_until_is_bounded() -> None:
    now = [0.0]
    values = iter(["pending", "pending", "ready"])

    def sleep(seconds: float) -> None:
        now[0] += seconds

    value, history = poll_until(
        lambda: next(values),
        lambda item: item == "ready",
        timeout_seconds=2,
        interval_seconds=0.5,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    assert value == "ready" and len(history) == 3
    now[0] = 0
    value, history = poll_until(
        lambda: "pending",
        lambda item: False,
        timeout_seconds=1,
        interval_seconds=0.6,
        clock=lambda: now[0],
        sleeper=sleep,
    )
    assert value is None and len(history) == 3


def test_generation_report_redacts_environment_secret(settings, canonical_recording, fake_generator, monkeypatch) -> None:
    monkeypatch.setenv("API_TOKEN", "seeded-report-secret")
    service = OrchestratorService(settings, generator=fake_generator)
    outcome = service.create_review(canonical_recording)
    approved = service.approve_plan(outcome.plan.plan_id, ApprovalRequest())
    normalized = outcome.normalized
    report, path = service.reporter.build(
        normalized,
        approved,
        {"generatedFiles": ["README.md"]},
        {
            "success": False,
            "sanitizedOutput": (
                "failure seeded-report-secret clientSecret=REPORT-CLIENT-LEAK "
                "passwordHash=REPORT-HASH-LEAK authorizationValue=REPORT-AUTH-LEAK"
            ),
        },
    )
    report_json = report.model_dump_json()
    report_html = path.read_text(encoding="utf-8")
    for secret in (
        "seeded-report-secret",
        "REPORT-CLIENT-LEAK",
        "REPORT-HASH-LEAK",
        "REPORT-AUTH-LEAK",
    ):
        assert secret not in report_json
        assert secret not in report_html
    assert report.ui_coverage_map
    assert report.ui_coverage_map[0].actions
    assert report.ui_coverage_map[0].actions[0].operation_ids
    assert report.api_inventory
    assert any(operation.examples for operation in report.api_inventory)
    assert report.test_matrix
    assert report.plan_assumptions == approved.assumptions
    assert report.plan_uncertainties == approved.uncertainties
    assert report.data_dependencies
    for required_field in (
        "uiCoverageMap",
        "apiInventory",
        "testMatrix",
        "planAssumptions",
        "planUncertainties",
        "dataDependencies",
    ):
        assert required_field in report_html


def test_persisted_generation_can_resume_after_code_generation(settings, canonical_recording, fake_generator) -> None:
    service = OrchestratorService(settings, generator=fake_generator)
    outcome = service.create_review(canonical_recording)
    approved = service.approve_plan(outcome.plan.plan_id, ApprovalRequest())
    result = service.generate(
        outcome.normalized.recording_id,
        approved,
        project_name="resume-tests",
        explicit_approval=False,
        validate_project=False,
    )
    completed = service.get_run(result.generation_id)
    partial_state = dict(completed.state)
    partial_state.pop("validation", None)
    partial_state.pop("report", None)
    interrupted = completed.model_copy(
        update={"status": "generating", "current_node": "code_generation", "state": partial_state}
    )
    service.repository.save_run(interrupted)
    resumed = service.resume(interrupted.run_id)
    assert resumed.status == "completed"
    assert resumed.current_node == "report"
