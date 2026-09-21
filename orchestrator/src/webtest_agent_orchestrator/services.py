from __future__ import annotations

import html
import importlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol, TypeVar
from uuid import uuid4

from .config import Settings
from .exploration import ExplorationAgent
from .graph import GenerationGraph, GraphState, PlanningGraph
from .llm import StructuredProvider, configured_provider, provider_exploration_action
from .normalization import CaptureNormalizer
from .persistence import SQLiteRepository
from .planning import FlowPlanner, ScenarioDesigner
from .schemas import (
    ApprovalRequest,
    ExplorationAction,
    ExplorationRequest,
    GenerationReport,
    GenerationResult,
    GraphRun,
    NormalizedRecording,
    PlanPatch,
    Recording,
    ReviewPlan,
    ScenarioKind,
    ValidationResult,
)
from .security import redact, redact_known_secrets, sanitize_recording


class NotFoundError(ValueError):
    pass


class ApprovalRequiredError(ValueError):
    pass


class GeneratorBackend(Protocol):
    name: str

    def generate(self, plan: ReviewPlan, output_root: Path, project_name: str) -> dict[str, Any]: ...


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


class SiblingGeneratorBackend:
    name = "webtest-generator"

    def __init__(self, generator_root: Path):
        self.generator_root = generator_root.resolve()

    def _load(self) -> Callable[..., Any] | None:
        module_file = self.generator_root / "webtest_generator" / "generator.py"
        if not module_file.exists():
            return None
        root_text = str(self.generator_root)
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        module = importlib.import_module("webtest_generator.generator")
        function = getattr(module, "generate_project", None)
        if not callable(function):
            raise RuntimeError("webtest_generator.generator.generate_project is not callable")
        return function

    def generate(self, plan: ReviewPlan, output_root: Path, project_name: str) -> dict[str, Any]:
        function = self._load()
        if function is None:
            return self._fallback(plan, output_root, project_name)
        manifest = function(
            plan=plan.model_dump(mode="json", by_alias=True),
            output_root=output_root,
            project_name=project_name,
        )
        if hasattr(manifest, "model_dump"):
            manifest = manifest.model_dump(mode="json", by_alias=True)
        elif hasattr(manifest, "__dict__") and not isinstance(manifest, dict):
            manifest = vars(manifest)
        if not isinstance(manifest, dict):
            raise RuntimeError("generator returned a non-object manifest")
        return redact(manifest)

    def _fallback(self, plan: ReviewPlan, output_root: Path, project_name: str) -> dict[str, Any]:
        """Sanitized handoff used only when the sibling generator is absent."""
        project_path = (output_root / project_name).resolve()
        if not _inside(output_root, project_path):
            raise ValueError("project path escapes the configured generated root")
        project_path.mkdir(parents=True, exist_ok=True)
        plan_path = project_path / "approved-plan.json"
        plan_path.write_text(
            json.dumps(redact(plan.model_dump(mode="json", by_alias=True)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        manifest = {
            "projectPath": str(project_path),
            "generatedFiles": [str(plan_path.relative_to(project_path))],
            "generator": "sanitized-plan-handoff",
            "warning": "The sibling Java generator was unavailable; only a deterministic plan handoff was written.",
        }
        manifest_path = project_path / "generation-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        manifest["generatedFiles"].append(str(manifest_path.relative_to(project_path)))
        return manifest


class ValidationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, project_path: Path, *, run_tests: bool = True, max_repair_attempts: int = 2, plan: ReviewPlan | None = None) -> ValidationResult:
        root = self.settings.generated_root.resolve()
        project_path = project_path.resolve()
        if not _inside(root, project_path):
            raise ValueError("validation is limited to the configured generated root")
        pom = project_path / "pom.xml"
        if not pom.is_file():
            return ValidationResult(
                success=False,
                command=[],
                exit_code=None,
                attempts=0,
                elapsed_seconds=0,
                sanitized_output="pom.xml was not generated",
            )
        maven = shutil.which("mvn")
        if not maven:
            return ValidationResult(
                success=False,
                command=["mvn"],
                exit_code=None,
                attempts=0,
                elapsed_seconds=0,
                sanitized_output="Maven executable was not found on PATH",
            )
        goal = "test" if run_tests else "test-compile"
        command = [maven, "-B", "-ntp", "-f", str(pom), goal]
        started = time.monotonic()
        attempts = 0
        output = ""
        exit_code: int | None = None
        timed_out = False
        while True:
            attempts += 1
            try:
                completed = subprocess.run(
                    command,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=self.settings.validation_timeout_seconds,
                    check=False,
                )
                exit_code = completed.returncode
                output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                output = f"Validation timed out after {self.settings.validation_timeout_seconds} seconds\n{exc.stdout or ''}\n{exc.stderr or ''}"
                exit_code = None
            if exit_code == 0:
                break
            if timed_out or attempts > max_repair_attempts or not self._repair(project_path, output, plan):
                break
        elapsed = time.monotonic() - started
        safe_output = redact_known_secrets(output)[-100_000:]
        return ValidationResult(
            success=exit_code == 0,
            command=["mvn", "-B", "-ntp", "-f", "pom.xml", goal],
            exit_code=exit_code,
            attempts=attempts,
            elapsed_seconds=round(elapsed, 3),
            sanitized_output=safe_output,
            timed_out=timed_out,
        )

    def _repair(self, project_path: Path, diagnostics: str, plan: ReviewPlan | None) -> bool:
        """Call an optional deterministic generator repair hook; never alter scenario intent here."""
        root_text = str(self.settings.generator_root.resolve())
        if root_text not in sys.path:
            sys.path.insert(0, root_text)
        try:
            module = importlib.import_module("webtest_generator.generator")
        except ImportError:
            return False
        repair = getattr(module, "repair_project", None)
        if not callable(repair):
            return False
        return bool(
            repair(
                project_path=project_path,
                diagnostics=redact_known_secrets(diagnostics),
                plan=plan.model_dump(mode="json", by_alias=True) if plan else None,
            )
        )


T = TypeVar("T")


def poll_until(
    probe: Callable[[], T],
    done: Callable[[T], bool],
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.1,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[T | None, list[T]]:
    if timeout_seconds < 0 or interval_seconds < 0:
        raise ValueError("poll timeout and interval must be non-negative")
    deadline = clock() + timeout_seconds
    history: list[T] = []
    while True:
        value = probe()
        history.append(value)
        if done(value):
            return value, history
        remaining = deadline - clock()
        if remaining <= 0:
            return None, history
        sleeper(min(interval_seconds, remaining))


class ReportService:
    def __init__(self, settings: Settings, repository: SQLiteRepository):
        self.settings = settings
        self.repository = repository

    def build(
        self,
        normalized: NormalizedRecording,
        plan: ReviewPlan,
        generation: dict[str, Any],
        validation: dict[str, Any],
    ) -> tuple[GenerationReport, Path]:
        scenarios = [scenario for workflow in plan.workflows for scenario in workflow.scenarios if scenario.enabled]
        correlations = {item.action_id: item.operation_ids for item in normalized.correlations}
        ui_coverage_map = [
            {
                "pageUrl": page,
                "actions": [
                    {
                        "actionId": action.id,
                        "actionType": action.type.value,
                        "operationIds": correlations.get(action.id, []),
                    }
                    for action in normalized.actions
                    if action.page_url == page
                ],
            }
            for page in normalized.pages_visited
        ]
        api_inventory = [
            {
                "operationId": operation.operation_id,
                "method": operation.method,
                "origin": operation.origin,
                "normalizedPath": operation.normalized_path,
                "pathParameters": [item.model_dump(mode="json", by_alias=True) for item in operation.path_parameters],
                "observedStatuses": operation.observed_statuses,
                "examples": [
                    {
                        "requestId": example.request_id,
                        "sanitizedUrl": example.url,
                        "requestBody": example.request_body,
                        "responseStatus": example.response_status,
                        "responseBody": example.response_body,
                        "relatedUiActionId": example.related_ui_action_id,
                    }
                    for example in operation.examples
                ],
            }
            for operation in normalized.operations
        ]
        test_matrix = [
            {
                "workflowId": workflow.workflow_id,
                "workflowName": workflow.name,
                "scenarioId": scenario.scenario_id,
                "scenarioName": scenario.name,
                "kind": scenario.kind,
                "enabled": scenario.enabled,
                "stepIds": scenario.step_ids,
                "expectedStatuses": scenario.expected_statuses,
                "groups": scenario.groups,
            }
            for workflow in plan.workflows
            for scenario in workflow.scenarios
        ]
        dependency_by_key: dict[tuple[str, str, str, str, str], Any] = {}
        for workflow in plan.workflows:
            for step in workflow.steps:
                for dependency in step.dependencies:
                    key = (
                        dependency.source_step_id,
                        dependency.source_json_path,
                        dependency.target_step_id,
                        dependency.target_location,
                        dependency.variable_name,
                    )
                    dependency_by_key[key] = dependency
        report_id = "report-" + uuid4().hex
        compile_result = {
            "success": validation.get("success", False),
            "exitCode": validation.get("exitCode"),
            "attempts": validation.get("attempts", 0),
            "timedOut": validation.get("timedOut", False),
        }
        diagnostics = []
        if validation.get("sanitizedOutput") and not validation.get("success"):
            diagnostics.append(redact_known_secrets(str(validation["sanitizedOutput"]))[-20_000:])
        report = GenerationReport(
            report_id=report_id,
            recording_id=normalized.recording_id,
            plan_id=plan.plan_id,
            pages_visited=normalized.pages_visited,
            ui_actions_executed=len(normalized.actions),
            api_operations_observed=len(normalized.operations),
            normalized_endpoints=[f"{op.method} {op.normalized_path}" for op in normalized.operations],
            workflows_discovered=[workflow.name for workflow in plan.workflows],
            positive_scenarios_generated=sum(s.kind in {ScenarioKind.POSITIVE, ScenarioKind.ASYNCHRONOUS} for s in scenarios),
            negative_scenarios_generated=sum(s.kind not in {ScenarioKind.POSITIVE, ScenarioKind.ASYNCHRONOUS} for s in scenarios),
            unsupported_operations=normalized.unsupported_traffic,
            unvisited_areas=[],
            generated_files=list(generation.get("generatedFiles", generation.get("generated_files", []))),
            compile_result=compile_result,
            test_results={"executed": bool(validation.get("command")), "success": validation.get("success", False)},
            failures_and_diagnostics=diagnostics,
            coverage_limitations=[
                "Coverage describes only pages and API traffic observed during this recording.",
                "WebSockets, SSE, gRPC, protobuf, binary bodies, uploads, multi-tab, CAPTCHA, and payment flows are report-only in version one.",
                "Disabled scenarios require human evidence or expected results before generation.",
            ],
            source_recording_ids=[normalized.recording_id],
            ui_coverage_map=ui_coverage_map,
            api_inventory=api_inventory,
            test_matrix=test_matrix,
            plan_assumptions=plan.assumptions,
            plan_uncertainties=plan.uncertainties,
            data_dependencies=list(dependency_by_key.values()),
        )
        safe_report = GenerationReport.model_validate(redact(report.model_dump(mode="json", by_alias=True)))
        path = self.settings.report_root / f"{report_id}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(safe_report.model_dump(mode="json", by_alias=True), indent=2, sort_keys=True)
        document = (
            "<!doctype html><html><head><meta charset='utf-8'><title>WebTest Agent generation report</title>"
            "<style>body{font:15px system-ui;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#172033}"
            "pre{white-space:pre-wrap;background:#f5f7fb;padding:1rem;border-radius:8px}</style></head>"
            f"<body><h1>WebTest Agent generation report</h1><pre>{html.escape(payload)}</pre></body></html>"
        )
        path.write_text(document, encoding="utf-8")
        self.repository.save_report(safe_report, path)
        return safe_report, path


@dataclass(slots=True)
class ReviewOutcome:
    plan: ReviewPlan
    normalized: NormalizedRecording
    run: GraphRun
    warnings: list[str]


class OrchestratorService:
    def __init__(
        self,
        settings: Settings,
        repository: SQLiteRepository | None = None,
        generator: GeneratorBackend | None = None,
        provider: StructuredProvider | None = None,
    ):
        self.settings = settings
        settings.ensure_directories()
        self.repository = repository or SQLiteRepository(settings.db_path)
        self.normalizer = CaptureNormalizer(
            max_requests=settings.max_recording_requests,
            max_payload_bytes=settings.max_payload_bytes,
        )
        self.planner = FlowPlanner()
        self.designer = ScenarioDesigner()
        self.explorer = ExplorationAgent()
        self.provider = provider or configured_provider(settings.llm_provider, settings.openai_model)
        self.generator = generator or SiblingGeneratorBackend(settings.generator_root)
        self.validator = ValidationService(settings)
        self.reporter = ReportService(settings, self.repository)

    def next_action(self, request: ExplorationRequest) -> ExplorationAction:
        suggested = provider_exploration_action(self.provider, request)
        if suggested is not None:
            return self.explorer.validate_model_action(request, suggested)
        return self.explorer.next_action(request)

    def create_review(self, recording: Recording) -> ReviewOutcome:
        safe_recording = sanitize_recording(recording, max_payload_bytes=self.settings.max_payload_bytes)
        run_id = "run-" + uuid4().hex
        persisted_run: GraphRun | None = None

        def transition(node: str, state: GraphState) -> None:
            nonlocal persisted_run
            if "normalized" not in state:
                return
            normalized = NormalizedRecording.model_validate(state["normalized"])
            self.repository.save_recording(safe_recording, normalized)
            plan = ReviewPlan.model_validate(state["plan"]) if "plan" in state else None
            if plan is not None:
                self.repository.save_plan(plan)
            persisted_run = GraphRun(
                run_id=run_id,
                recording_id=normalized.recording_id,
                plan_id=plan.plan_id if plan else None,
                status="awaiting_review" if node == "human_review" else "running",
                current_node=node,
                graph_backend=graph.backend_name,
                state=state,
                updated_at=datetime.now(timezone.utc),
            )
            self.repository.save_run(persisted_run)

        graph = PlanningGraph(self.normalizer, self.planner, self.designer, transition)
        initial: GraphState = {
            "run_id": run_id,
            "recording": safe_recording.model_dump(mode="json", by_alias=True),
            "status": "running",
            "current_node": "start",
        }
        result = graph.invoke(initial)
        normalized = NormalizedRecording.model_validate(result["normalized"])
        plan = ReviewPlan.model_validate(result["plan"])
        if persisted_run is None:
            raise RuntimeError("planning graph completed without persisting state")
        warnings = list(plan.uncertainties)
        if normalized.unsupported_traffic:
            warnings.append(f"{len(normalized.unsupported_traffic)} request(s) were excluded or unsupported")
        return ReviewOutcome(plan=plan, normalized=normalized, run=persisted_run, warnings=warnings)

    def get_plan(self, plan_id: str) -> ReviewPlan:
        plan = self.repository.get_plan(plan_id)
        if not plan:
            raise NotFoundError("plan not found")
        return plan

    def edit_plan(self, plan_id: str, patch: PlanPatch, revision: int) -> ReviewPlan:
        current = self.get_plan(plan_id)
        updates = patch.model_dump(exclude_none=True)
        if "workflows" in updates:
            updates["workflows"] = [workflow.model_copy(update={"approval": "pending"}) for workflow in patch.workflows or []]
        updates.update(
            revision=current.revision + 1,
            status="draft",
            updated_at=datetime.now(timezone.utc),
        )
        updated = current.model_copy(update=updates)
        self.designer.design(updated)
        return self.repository.save_plan(updated, expected_revision=revision)

    def approve_plan(self, plan_id: str, request: ApprovalRequest) -> ReviewPlan:
        current = self.get_plan(plan_id)
        wanted = set(request.workflow_ids) or {workflow.workflow_id for workflow in current.workflows}
        known = {workflow.workflow_id for workflow in current.workflows}
        if not wanted.issubset(known):
            raise ValueError("approval references an unknown workflow")
        workflows = [
            workflow.model_copy(update={"approval": "approved" if workflow.workflow_id in wanted else "rejected"})
            for workflow in current.workflows
        ]
        updated = current.model_copy(
            update={
                "workflows": workflows,
                "status": "approved",
                "revision": current.revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self.repository.save_plan(updated, expected_revision=current.revision)

    def reject_plan(self, plan_id: str) -> ReviewPlan:
        current = self.get_plan(plan_id)
        workflows = [workflow.model_copy(update={"approval": "rejected"}) for workflow in current.workflows]
        updated = current.model_copy(
            update={
                "workflows": workflows,
                "status": "rejected",
                "revision": current.revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self.repository.save_plan(updated, expected_revision=current.revision)

    def _resolve_recording(self, identifier: str) -> NormalizedRecording:
        normalized = self.repository.get_normalized(identifier) or self.repository.normalized_for_session(identifier)
        if not normalized:
            raise NotFoundError("recording not found")
        return normalized

    def _verify_plan(self, plan: ReviewPlan, normalized: NormalizedRecording) -> None:
        if plan.recording_id != normalized.recording_id:
            raise ValueError("plan does not belong to the supplied recording")
        observed = [operation.model_dump(mode="json", by_alias=True) for operation in normalized.operations]
        proposed = [operation.model_dump(mode="json", by_alias=True) for operation in plan.api_inventory]
        if proposed != observed:
            raise ValueError("the approved plan modified the immutable observed API inventory")
        self.designer.design(plan)

    def generate(
        self,
        recording_identifier: str,
        plan: ReviewPlan,
        *,
        project_name: str,
        explicit_approval: bool,
        validate_project: bool,
    ) -> GenerationResult:
        normalized = self._resolve_recording(recording_identifier)
        self._verify_plan(plan, normalized)
        if not plan.is_approved:
            if not explicit_approval:
                raise ApprovalRequiredError("code generation requires an approved plan")
            workflows = [
                workflow.model_copy(update={"approval": "approved" if workflow.approval != "rejected" else "rejected"})
                for workflow in plan.workflows
            ]
            plan = plan.model_copy(
                update={
                    "status": "approved",
                    "workflows": workflows,
                    "revision": plan.revision + 1,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        if not plan.is_approved:
            raise ApprovalRequiredError("at least one workflow must be approved")
        plan = self.repository.save_plan(plan)
        run_id = "run-" + uuid4().hex
        state: GraphState = {
            "run_id": run_id,
            "normalized": normalized.model_dump(mode="json", by_alias=True),
            "plan": plan.model_dump(mode="json", by_alias=True),
            "status": "generating",
            "current_node": "human_review",
            "generation": {"projectName": project_name, "validateProject": validate_project},
        }
        initial_run = GraphRun(
            run_id=run_id,
            recording_id=normalized.recording_id,
            plan_id=plan.plan_id,
            status="generating",
            current_node="human_review",
            graph_backend="pending",
            state=state,
        )
        self.repository.save_run(initial_run)
        graph = self._generation_graph(run_id, normalized, plan, project_name, validate_project)
        try:
            result_state = graph.invoke(state)
        except Exception as exc:
            failed = initial_run.model_copy(
                update={
                    "status": "failed",
                    "current_node": "generation_error",
                    "graph_backend": graph.backend_name,
                    "state": state,
                    "error": redact_known_secrets(str(exc)),
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self.repository.save_run(failed)
            raise
        generation = result_state["generation"]
        return GenerationResult(
            generation_id=run_id,
            plan_id=plan.plan_id,
            project_name=project_name,
            project_path=str(generation["projectPath"]),
            generated_files=list(generation.get("generatedFiles", [])),
            generator=str(generation.get("generator", self.generator.name)),
            compile_result=result_state.get("validation", {}),
            test_result=result_state.get("validation", {}),
            report_id=result_state.get("report", {}).get("reportId"),
        )

    def _generation_graph(
        self,
        run_id: str,
        normalized: NormalizedRecording,
        plan: ReviewPlan,
        project_name: str,
        validate_project: bool,
    ) -> GenerationGraph:
        def code_generation(state: GraphState) -> dict[str, Any]:
            manifest = self.generator.generate(plan, self.settings.generated_root, project_name)
            project_value = manifest.get(
                "projectPath",
                manifest.get("project_path", manifest.get("projectDirectory", self.settings.generated_root / project_name)),
            )
            project_path = Path(project_value).resolve()
            if not _inside(self.settings.generated_root, project_path):
                raise ValueError("generator returned a project path outside the configured root")
            files = manifest.get("generatedFiles", manifest.get("generated_files", manifest.get("files", [])))
            file_names = [item.get("path", "") if isinstance(item, dict) else str(item) for item in files]
            file_names = [item for item in file_names if item]
            return {
                "generation": {
                    **redact(manifest),
                    "projectPath": str(project_path),
                    "generatedFiles": file_names,
                    "generator": manifest.get("generator", self.generator.name),
                    "projectName": project_name,
                    "validateProject": validate_project,
                }
            }

        def validation_and_repair(state: GraphState) -> dict[str, Any]:
            if not validate_project:
                return {
                    "validation": ValidationResult(
                        success=False,
                        command=[],
                        exit_code=None,
                        attempts=0,
                        elapsed_seconds=0,
                        sanitized_output="Validation was not requested",
                    ).model_dump(mode="json", by_alias=True)
                }
            result = self.validator.validate(Path(state["generation"]["projectPath"]), plan=plan)
            return {"validation": result.model_dump(mode="json", by_alias=True)}

        def report(state: GraphState) -> dict[str, Any]:
            report_value, report_path = self.reporter.build(
                normalized,
                plan,
                state["generation"],
                state.get("validation", {}),
            )
            return {
                "report": {
                    **report_value.model_dump(mode="json", by_alias=True),
                    "reportPath": str(report_path),
                }
            }

        graph: GenerationGraph

        def transition(node: str, state: GraphState) -> None:
            run = GraphRun(
                run_id=run_id,
                recording_id=normalized.recording_id,
                plan_id=plan.plan_id,
                status="completed" if node == "report" else "generating",
                current_node=node,
                graph_backend=graph.backend_name,
                state=state,
                updated_at=datetime.now(timezone.utc),
            )
            self.repository.save_run(run)

        graph = GenerationGraph(code_generation, validation_and_repair, report, transition)
        return graph

    def get_run(self, run_id: str) -> GraphRun:
        run = self.repository.get_run(run_id)
        if not run:
            raise NotFoundError("run not found")
        return run

    def resume(self, run_id: str) -> GraphRun:
        run = self.get_run(run_id)
        if run.status in {"completed", "awaiting_review", "approved"}:
            return run
        state = GraphState(run.state)
        normalized = NormalizedRecording.model_validate(state["normalized"])
        plan = ReviewPlan.model_validate(state["plan"])
        generation = state.get("generation", {})
        project_name = str(generation.get("projectName", "webtest-generated-tests"))
        validate_project = bool(generation.get("validateProject", False))
        graph = self._generation_graph(run_id, normalized, plan, project_name, validate_project)
        result = graph.invoke(state, start_after=run.current_node if run.current_node in {"code_generation", "validation_and_repair"} else None)
        return self.get_run(run_id) if result else run
