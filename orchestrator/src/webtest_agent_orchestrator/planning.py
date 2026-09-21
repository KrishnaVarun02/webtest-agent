from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit

from .schemas import (
    AssertionSpec,
    DataDependency,
    FlowStep,
    MutationSpec,
    NormalizedOperation,
    NormalizedRecording,
    ReviewPlan,
    Scenario,
    ScenarioKind,
    Workflow,
)


def _stable_id(prefix: str, *parts: str) -> str:
    return prefix + "-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:14]


def _flatten(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)) else f"{path}[{json.dumps(str(key))}]"
            result.extend(_flatten(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value[:20]):
            result.extend(_flatten(item, f"{path}[{index}]"))
    elif value is not None and not (isinstance(value, str) and value.startswith("${")):
        result.append((path, value))
    return result


def _target_values(operation: NormalizedOperation) -> list[tuple[str, Any]]:
    values: list[tuple[str, Any]] = []
    for example in operation.examples:
        for index, segment in enumerate(urlsplit(example.url).path.strip("/").split("/")):
            values.append((f"path[{index}]", segment))
        values.extend((f"query:{path[2:]}", value) for path, value in _flatten(example.query_parameters))
        values.extend((f"body:{path}", value) for path, value in _flatten(example.request_body))
    return values


def _source_values(operation: NormalizedOperation) -> list[tuple[str, Any]]:
    values: list[tuple[str, Any]] = []
    for example in operation.examples:
        if example.response_status is not None and 200 <= example.response_status < 300:
            values.extend(_flatten(example.response_body))
    return values


def _token_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if re.search(r"(?:^|_)(?:access_?token|token|jwt|bearer)(?:$|_)", str(key), re.I) or re.search(
                r"(?:accessToken|refreshToken|idToken)$", str(key), re.I
            ):
                paths.append(child)
            paths.extend(_token_paths(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value[:10]):
            paths.extend(_token_paths(item, f"{path}[{index}]"))
    return paths


def _auth_token_path(operation: NormalizedOperation) -> str | None:
    for example in operation.examples:
        if example.response_status is not None and 200 <= example.response_status < 300:
            paths = _token_paths(example.response_body)
            if paths:
                return paths[0]
    return None


def _variable_name(path: str, fallback: str = "value") -> str:
    candidate = re.sub(r"[^A-Za-z0-9]+", "_", path.strip("$.")).strip("_") or fallback
    if candidate[0].isdigit():
        candidate = "value_" + candidate
    return candidate.lower()


def _dependency_candidate(source_path: str, source_value: Any, target_location: str) -> bool:
    leaf = re.split(r"[.\[\]]+", source_path.lower())[-1]
    identifier_name = bool(re.search(r"(?:^|_)(?:id|uuid|token|tracking|reference|key)(?:$|_)", leaf)) or leaf.endswith("id")
    text = str(source_value)
    identifier_shape = bool(
        re.fullmatch(r"[0-9a-f]{8}-[0-9a-f-]{20,}", text, re.I)
        or re.fullmatch(r"[0-9a-f]{16,64}", text, re.I)
        or re.fullmatch(r"[1-9][0-9]{5,18}", text)
    )
    return identifier_name or (target_location.startswith("path[") and identifier_shape)


def infer_dependencies(operations: list[NormalizedOperation], step_ids: dict[str, str]) -> dict[str, list[DataDependency]]:
    dependencies: dict[str, list[DataDependency]] = defaultdict(list)
    prior: list[NormalizedOperation] = []
    for target in operations:
        target_values = _target_values(target)
        seen: set[tuple[str, str, str]] = set()
        for source in prior:
            for source_path, source_value in _source_values(source):
                for target_location, target_value in target_values:
                    if (
                        type(source_value) is type(target_value)
                        and source_value == target_value
                        and _dependency_candidate(source_path, source_value, target_location)
                    ):
                        marker = (source.operation_id, source_path, target_location)
                        if marker in seen:
                            continue
                        seen.add(marker)
                        dependencies[target.operation_id].append(
                            DataDependency(
                                source_step_id=step_ids[source.operation_id],
                                source_json_path=source_path,
                                target_step_id=step_ids[target.operation_id],
                                target_location=target_location,
                                variable_name=_variable_name(source_path),
                                confidence="high",
                                evidence="The same observed value appears in an earlier response and this request",
                            )
                        )
            # At most a small, readable set per source/target pair.
            dependencies[target.operation_id] = dependencies[target.operation_id][:8]
        prior.append(target)
    token_sources: list[tuple[NormalizedOperation, str]] = []
    for operation in operations:
        token_path = _auth_token_path(operation)
        if token_path:
            token_sources.append((operation, token_path))
            continue
        if operation.auth_evidence and token_sources:
            source, source_path = token_sources[-1]
            marker = (step_ids[source.operation_id], source_path, "header:Authorization")
            if not any(
                (item.source_step_id, item.source_json_path, item.target_location) == marker
                for item in dependencies[operation.operation_id]
            ):
                dependencies[operation.operation_id].append(
                    DataDependency(
                        source_step_id=step_ids[source.operation_id],
                        source_json_path=source_path,
                        target_step_id=step_ids[operation.operation_id],
                        target_location="header:Authorization",
                        variable_name="api_token",
                        confidence="high",
                        evidence="A successful setup response contains a token-named field and this request used authentication",
                    )
                )
    return dependencies


def _first_time(operation: NormalizedOperation) -> datetime:
    return min((example.timestamp for example in operation.examples), default=datetime.max.replace(tzinfo=timezone.utc))


def _human_operation_name(operation: NormalizedOperation) -> str:
    path = re.sub(r"\{[^}]+\}", "item", operation.normalized_path).strip("/") or "root"
    return f"{operation.method.title()} {path.replace('/', ' / ')}"


def _successful_statuses(operation: NormalizedOperation) -> list[int]:
    return [status for status in operation.observed_statuses if 200 <= status < 400]


def _failure_statuses(operation: NormalizedOperation) -> list[int]:
    return [status for status in operation.observed_statuses if 400 <= status < 500]


def _request_body_fields(operation: NormalizedOperation) -> list[tuple[str, Any]]:
    fields: dict[str, Any] = {}
    for example in operation.examples:
        if example.response_status is None or example.response_status < 400:
            for path, value in _flatten(example.request_body):
                fields.setdefault(path, value)
    return list(fields.items())


def _error_text(operation: NormalizedOperation) -> str:
    return " ".join(
        json.dumps(example.response_body, default=str)
        for example in operation.examples
        if example.response_status is not None and 400 <= example.response_status < 500
    ).lower()


def _assertions(operation: NormalizedOperation) -> list[AssertionSpec]:
    assertions: list[AssertionSpec] = []
    statuses = _successful_statuses(operation)
    if statuses:
        assertions.append(
            AssertionSpec(kind="status", expected=statuses, evidence="Observed successful response statuses")
        )
    if operation.response_content_types:
        assertions.append(
            AssertionSpec(
                kind="content_type",
                expected=operation.response_content_types,
                evidence="Observed response Content-Type headers",
            )
        )
    schema = operation.response_schema
    if schema.get("type") == "object":
        for field in schema.get("observedRequired", [])[:12]:
            field_schema = schema.get("properties", {}).get(field, {})
            assertions.append(
                AssertionSpec(
                    kind="field_present",
                    path=f"$.{field}",
                    expected=True,
                    evidence="Field was present in every successful recorded example",
                )
            )
            if field_schema.get("format") in {"uuid", "date-time"}:
                assertions.append(
                    AssertionSpec(
                        kind="format",
                        path=f"$.{field}",
                        expected=field_schema["format"],
                        evidence="Recorded values consistently matched this dynamic format",
                    )
                )
    return assertions


def _negative_scenarios(workflow_id: str, step: FlowStep, operation: NormalizedOperation) -> list[Scenario]:
    scenarios: list[Scenario] = []
    failures = _failure_statuses(operation)
    error_text = _error_text(operation)
    body_fields = _request_body_fields(operation)
    if body_fields:
        field_path, field_value = body_fields[0]
        required_evidence = "required" in error_text and field_path.split(".")[-1].lower() in error_text
        expected = failures if required_evidence else []
        scenarios.append(
            Scenario(
                scenario_id=_stable_id("scenario", workflow_id, step.step_id, "missing", field_path),
                workflow_id=workflow_id,
                name=f"Reject {step.name} when {field_path} is missing",
                kind=ScenarioKind.MISSING_REQUIRED_FIELD,
                enabled=required_evidence,
                step_ids=[step.step_id],
                mutation=MutationSpec(
                    location="body",
                    path=field_path,
                    operation="remove",
                    evidence=(
                        "A recorded validation response identified this field as required"
                        if required_evidence
                        else "The field exists in a valid request; requiredness needs review"
                    ),
                ),
                expected_statuses=expected,
                groups=["negative"],
                review_notes=[] if required_evidence else ["Enable only after confirming the field is required and adding an expected status"],
                uncertainty=None if required_evidence else "Requiredness was not established by recording evidence",
            )
        )
        invalid_value = "not-a-number" if isinstance(field_value, (int, float)) and not isinstance(field_value, bool) else 42
        type_evidence = ("type" in error_text or "invalid" in error_text) and field_path.split(".")[-1].lower() in error_text
        scenarios.append(
            Scenario(
                scenario_id=_stable_id("scenario", workflow_id, step.step_id, "invalid-type", field_path),
                workflow_id=workflow_id,
                name=f"Reject {step.name} when {field_path} has an invalid type",
                kind=ScenarioKind.INVALID_TYPE,
                enabled=type_evidence,
                step_ids=[step.step_id],
                mutation=MutationSpec(
                    location="body",
                    path=field_path,
                    operation="replace",
                    value=invalid_value,
                    evidence=(
                        "A recorded validation response supports invalid-type behavior"
                        if type_evidence
                        else "The replacement differs from the observed valid JSON type; behavior needs review"
                    ),
                ),
                expected_statuses=failures if type_evidence else [],
                groups=["negative"],
                review_notes=[] if type_evidence else ["Enable only after supplying the expected status"],
                uncertainty=None if type_evidence else "Invalid-type handling was not observed",
            )
        )
    if operation.path_parameters:
        parameter = operation.path_parameters[-1]
        not_found_evidence = 404 in operation.observed_statuses
        scenarios.append(
            Scenario(
                scenario_id=_stable_id("scenario", workflow_id, step.step_id, "invalid-id", parameter.name),
                workflow_id=workflow_id,
                name=f"Handle a nonexistent {parameter.name} for {step.name}",
                kind=ScenarioKind.INVALID_IDENTIFIER,
                enabled=not_found_evidence,
                step_ids=[step.step_id],
                mutation=MutationSpec(
                    location="path",
                    path=parameter.name,
                    operation="replace",
                    value="00000000-0000-4000-8000-000000000000" if parameter.value_type == "uuid" else "999999999999999999",
                    evidence="The path segment was identified as a dynamic resource identifier",
                ),
                expected_statuses=[404] if not_found_evidence else [],
                groups=["negative"],
                review_notes=[] if not_found_evidence else ["The not-found status was not observed; confirm it before enabling"],
                uncertainty=None if not_found_evidence else "Nonexistent identifier behavior was not observed",
            )
        )
    if operation.auth_evidence:
        auth_failure = next((status for status in operation.observed_statuses if status in {401, 403}), None)
        scenarios.append(
            Scenario(
                scenario_id=_stable_id("scenario", workflow_id, step.step_id, "unauthorized"),
                workflow_id=workflow_id,
                name=f"Reject unauthenticated {step.name}",
                kind=ScenarioKind.UNAUTHORIZED,
                enabled=auth_failure is not None,
                step_ids=[step.step_id],
                mutation=MutationSpec(
                    location="header",
                    path="Authorization/Cookie",
                    operation="omit_auth",
                    evidence="Authentication headers or cookies were present in the recording",
                ),
                expected_statuses=[auth_failure] if auth_failure else [],
                groups=["negative"],
                review_notes=[] if auth_failure else ["Authentication is evidenced, but the failure status needs review"],
                uncertainty=None if auth_failure else "Unauthenticated behavior was not observed",
            )
        )
    return scenarios


class FlowPlanner:
    def plan(self, normalized: NormalizedRecording) -> ReviewPlan:
        workflows: list[Workflow] = []
        by_origin: dict[str, list[NormalizedOperation]] = defaultdict(list)
        for operation in normalized.operations:
            by_origin[operation.origin].append(operation)

        for origin, origin_operations in sorted(by_origin.items()):
            operations = sorted(origin_operations, key=_first_time)
            resource_names = sorted({op.resource_pattern.strip("/").split("/")[-1] or "root" for op in operations})
            label = ", ".join(resource_names[:3]) or urlsplit(origin).hostname or "API"
            workflow_id = _stable_id("workflow", normalized.recording_id, origin, *resource_names)
            step_ids = {op.operation_id: _stable_id("step", workflow_id, op.operation_id) for op in operations}
            dependency_map = infer_dependencies(operations, step_ids)
            steps: list[FlowStep] = []
            for order, operation in enumerate(operations, 1):
                dependencies = dependency_map.get(operation.operation_id, [])
                extracts = {
                    dependency.variable_name: dependency.source_json_path
                    for target_dependencies in dependency_map.values()
                    for dependency in target_dependencies
                    if dependency.source_step_id == step_ids[operation.operation_id]
                }
                destructive = operation.method == "DELETE" or "delete" in operation.normalized_path.lower()
                steps.append(
                    FlowStep(
                        step_id=step_ids[operation.operation_id],
                        operation_id=operation.operation_id,
                        name=_human_operation_name(operation),
                        order=order,
                        ui_action_ids=operation.related_ui_action_ids,
                        dependencies=dependencies,
                        extracts=extracts,
                        expected_statuses=_successful_statuses(operation),
                        state_changing=operation.state_changing,
                        destructive=destructive,
                        asynchronous=operation.asynchronous_evidence,
                        review_notes=[] if _successful_statuses(operation) else ["No successful status was observed"],
                    )
                )
            operation_by_id = {operation.operation_id: operation for operation in operations}
            setup_ids = [
                step.step_id
                for step in steps
                if any(marker in operation_by_id[step.operation_id].normalized_path.lower() for marker in ("login", "auth", "token", "session"))
            ]
            step_by_id = {step.step_id: step for step in steps}

            def required_steps(target_step_id: str) -> list[str]:
                required = set(setup_ids)
                pending = [target_step_id]
                while pending:
                    current_id = pending.pop()
                    current = step_by_id[current_id]
                    for dependency in current.dependencies:
                        if dependency.source_step_id not in required:
                            required.add(dependency.source_step_id)
                            pending.append(dependency.source_step_id)
                required.add(target_step_id)
                return [step.step_id for step in steps if step.step_id in required]

            positive_assertions: list[AssertionSpec] = []
            for operation in operations:
                positive_assertions.extend(_assertions(operation))
            positive = Scenario(
                scenario_id=_stable_id("scenario", workflow_id, "positive"),
                workflow_id=workflow_id,
                name=f"Complete the recorded {label} workflow",
                kind=ScenarioKind.POSITIVE,
                enabled=all(step.expected_statuses for step in steps),
                step_ids=[step.step_id for step in steps],
                expected_statuses=steps[-1].expected_statuses if steps else [],
                assertions=positive_assertions[:40],
                groups=["positive", "regression"] + (["destructive"] if any(step.destructive for step in steps) else []),
                review_notes=[] if all(step.expected_statuses for step in steps) else ["Confirm missing successful statuses before enabling"],
            )
            scenarios = [positive]
            for step in steps:
                candidates = _negative_scenarios(workflow_id, step, operation_by_id[step.operation_id])
                scenarios.extend(
                    scenario.model_copy(update={"step_ids": required_steps(step.step_id)})
                    for scenario in candidates
                )
            if any(step.asynchronous for step in steps):
                async_targets = [step.step_id for step in steps if step.asynchronous]
                async_required = {
                    required
                    for target in async_targets
                    for required in required_steps(target)
                }
                async_steps = [step.step_id for step in steps if step.step_id in async_required]
                scenarios.append(
                    Scenario(
                        scenario_id=_stable_id("scenario", workflow_id, "asynchronous"),
                        workflow_id=workflow_id,
                        name=f"Complete the asynchronous {label} flow with bounded polling",
                        kind=ScenarioKind.ASYNCHRONOUS,
                        enabled=True,
                        step_ids=async_steps,
                        expected_statuses=[],
                        groups=["positive", "asynchronous"],
                        review_notes=["Use the observed status operation and a bounded timeout; do not infer terminal values"],
                    )
                )
            cleanup_ids = [
                step.step_id
                for step in steps
                if step.destructive or "archive" in operation_by_id[step.operation_id].normalized_path.lower()
            ]
            uncertainties = sorted(
                {
                    scenario.uncertainty
                    for scenario in scenarios
                    if scenario.uncertainty
                }
            )
            workflows.append(
                Workflow(
                    workflow_id=workflow_id,
                    name=f"{label.title()} API workflow",
                    steps=steps,
                    scenarios=scenarios,
                    setup_step_ids=setup_ids,
                    cleanup_step_ids=cleanup_ids,
                    uncertainties=uncertainties,
                    destructive=any(step.destructive for step in steps),
                )
            )

        plan_id = _stable_id("plan", normalized.recording_id, "1")
        has_auth = any(operation.auth_evidence for operation in normalized.operations)
        uncertainties = sorted({uncertainty for workflow in workflows for uncertainty in workflow.uncertainties})
        assumptions = [
            "Only recorded evidence is asserted; disabled candidates require human confirmation.",
            "Generated negative cases mutate exactly one part of a known valid request.",
        ]
        return ReviewPlan(
            plan_id=plan_id,
            recording_id=normalized.recording_id,
            workflows=workflows,
            api_inventory=normalized.operations,
            assumptions=assumptions,
            uncertainties=uncertainties,
            missing_test_data=["API_AUTH"] if has_auth else [],
        )


class ScenarioDesigner:
    """Dedicated graph node validating scenario safety and evidence invariants."""

    def design(self, plan: ReviewPlan) -> ReviewPlan:
        operation_ids = {operation.operation_id for operation in plan.api_inventory}
        for workflow in plan.workflows:
            step_ids = {step.step_id for step in workflow.steps}
            if len(step_ids) != len(workflow.steps):
                raise ValueError(f"workflow {workflow.workflow_id} contains duplicate step ids")
            for step in workflow.steps:
                if step.operation_id not in operation_ids:
                    raise ValueError(f"step {step.step_id} references an unknown operation")
            for scenario in workflow.scenarios:
                if not set(scenario.step_ids).issubset(step_ids):
                    raise ValueError(f"scenario {scenario.scenario_id} references an unknown step")
                if scenario.kind != ScenarioKind.POSITIVE and scenario.kind != ScenarioKind.ASYNCHRONOUS:
                    if scenario.mutation is None:
                        raise ValueError(f"negative scenario {scenario.scenario_id} has no mutation")
        return plan
