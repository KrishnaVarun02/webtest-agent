from __future__ import annotations

from webtest_agent_orchestrator.adapters import recording_from_wire
from webtest_agent_orchestrator.normalization import CaptureNormalizer
from webtest_agent_orchestrator.planning import FlowPlanner, ScenarioDesigner
from webtest_agent_orchestrator.schemas import ScenarioKind


def _fixture_plan(extension_payload):
    recording = recording_from_wire(extension_payload)
    normalized = CaptureNormalizer().normalize(recording)
    return normalized, FlowPlanner().plan(normalized)


def test_extension_fixture_normalizes_and_plans(extension_payload) -> None:
    normalized, plan = _fixture_plan(extension_payload)
    assert normalized.filtered_request_count >= 1
    assert len(normalized.operations) == 7
    assert len(plan.workflows) == 1
    ScenarioDesigner().design(plan)
    workflow = plan.workflows[0]
    login = next(step for step in workflow.steps if "login" in step.name.lower())
    assert login.extracts["api_token"] == "$.accessToken"
    assert any(dependency.variable_name == "api_token" for step in workflow.steps for dependency in step.dependencies)


def test_dynamic_value_dependency_and_transitive_scenario_setup(extension_payload) -> None:
    _, plan = _fixture_plan(extension_payload)
    workflow = plan.workflows[0]
    create = next(step for step in workflow.steps if step.name.lower() == "post api / records")
    get = next(step for step in workflow.steps if step.name.lower() == "get api / records / item")
    assert any(dep.source_step_id == create.step_id and dep.target_location.startswith("path[") for dep in get.dependencies)
    missing = next(
        scenario
        for scenario in workflow.scenarios
        if scenario.kind == ScenarioKind.MISSING_REQUIRED_FIELD and scenario.enabled
    )
    assert workflow.setup_step_ids[0] in missing.step_ids
    assert missing.mutation is not None
    assert missing.mutation.operation == "remove"
    async_scenario = next(s for s in workflow.scenarios if s.kind == ScenarioKind.ASYNCHRONOUS)
    assert create.step_id in async_scenario.step_ids
    assert workflow.setup_step_ids[0] in async_scenario.step_ids


def test_negative_cases_do_not_invent_assertions(extension_payload) -> None:
    _, plan = _fixture_plan(extension_payload)
    candidates = [
        scenario
        for workflow in plan.workflows
        for scenario in workflow.scenarios
        if scenario.kind not in {ScenarioKind.POSITIVE, ScenarioKind.ASYNCHRONOUS}
    ]
    assert candidates
    assert all(scenario.mutation is not None for scenario in candidates)
    assert all(scenario.expected_statuses or not scenario.enabled for scenario in candidates)
    assert any(not scenario.enabled and scenario.uncertainty for scenario in candidates)


def test_dependency_inference_ignores_generic_repeated_status_values(extension_payload) -> None:
    _, plan = _fixture_plan(extension_payload)
    for workflow in plan.workflows:
        for step in workflow.steps:
            assert all(not dependency.source_json_path.lower().endswith(".status") for dependency in step.dependencies)

