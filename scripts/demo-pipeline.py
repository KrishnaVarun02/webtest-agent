#!/usr/bin/env python3
"""Run the fixture through planning, explicit approval, and Java generation.

This is a deterministic local demonstration helper.  It uses the same service,
LangGraph, SQLite repository, approval gate, and generator as the HTTP API.
It deliberately does not execute the generated tests; run-generated.sh keeps
that network action visible and separately authorized.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "orchestrator" / "src"))
sys.path.insert(0, str(ROOT / "generator"))

from webtest_agent_orchestrator.adapters import recording_from_wire  # noqa: E402
from webtest_agent_orchestrator.config import Settings  # noqa: E402
from webtest_agent_orchestrator.schemas import ApprovalRequest, PlanPatch, ReviewPlan  # noqa: E402
from webtest_agent_orchestrator.services import OrchestratorService  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an editable plan from the sample recording and optionally approve and generate it."
    )
    parser.add_argument(
        "--recording",
        type=Path,
        default=ROOT / "scripts" / "fixtures" / "sample-recording.json",
    )
    parser.add_argument("--project-name", default="webtest-e2e")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--approve-fixture",
        action="store_true",
        help=(
            "Apply the checked-in, human-reviewed sample decisions to the immutable observed inventory, "
            "approve them, and generate."
        ),
    )
    mode.add_argument(
        "--approve-plan-id",
        help="Approve and generate an existing persisted plan without recreating or discarding its edits.",
    )
    parser.add_argument(
        "--review-template",
        type=Path,
        default=ROOT / "generator" / "fixtures" / "approved-plan.json",
        help="Reviewed sample decisions used only with --approve-fixture.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Workflow to approve; repeat as needed. The default approves all non-rejected workflows.",
    )
    return parser


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def apply_reviewed_fixture(service: OrchestratorService, draft: ReviewPlan, template_path: Path) -> ReviewPlan:
    """Rebase sample-only reviewed decisions onto the draft's immutable inventory.

    The review template supplies step order, repeated poll/final-read steps, and
    evidence-backed assertions.  Endpoint bodies and examples always come from
    the freshly normalized recording. Unsupported template operations are
    dropped instead of invented (the capture does not contain archive/delete).
    """

    template = json.loads(template_path.read_text(encoding="utf-8"))
    actual_by_signature = {
        (operation.method.upper(), operation.normalized_path): operation.operation_id
        for operation in draft.api_inventory
    }
    actual_by_id = {operation.operation_id: operation for operation in draft.api_inventory}
    template_signatures = {
        str(operation["operationId"]): (
            str(operation["method"]).upper(),
            str(operation["normalizedPath"]),
        )
        for operation in template.get("apiInventory", [])
    }

    reviewed_workflows: list[dict[str, object]] = []
    for original in template.get("workflows", []):
        workflow = copy.deepcopy(original)
        reviewed_steps: list[dict[str, object]] = []
        for step in workflow.get("steps", []):
            signature = template_signatures.get(str(step.get("operationId")))
            actual_operation_id = actual_by_signature.get(signature) if signature else None
            if actual_operation_id is None:
                continue
            step["operationId"] = actual_operation_id
            reviewed_steps.append(step)
        retained_step_ids = {str(step["stepId"]) for step in reviewed_steps}
        workflow["steps"] = reviewed_steps
        workflow["scenarios"] = [
            scenario
            for scenario in workflow.get("scenarios", [])
            if set(map(str, scenario.get("stepIds", []))).issubset(retained_step_ids)
        ]
        workflow["setupStepIds"] = [
            step_id for step_id in workflow.get("setupStepIds", []) if step_id in retained_step_ids
        ]
        workflow["cleanupStepIds"] = [
            step_id for step_id in workflow.get("cleanupStepIds", []) if step_id in retained_step_ids
        ]
        reviewed_steps_by_id = {str(step["stepId"]): step for step in reviewed_steps}
        for scenario in workflow["scenarios"]:
            for assertion in scenario.get("assertions", []):
                path = str(assertion.get("path") or "")
                if assertion.get("kind") not in {"value", "final_state"} or not path.startswith("$."):
                    continue
                field = path[2:]
                if not field or "." in field or "[" in field:
                    continue
                observed_values: list[object] = []
                for step_id in scenario.get("stepIds", []):
                    step = reviewed_steps_by_id.get(str(step_id))
                    operation = actual_by_id.get(str(step.get("operationId"))) if step else None
                    if operation is None:
                        continue
                    for example in operation.examples:
                        if (
                            example.response_status is not None
                            and 200 <= example.response_status < 500
                            and isinstance(example.response_body, dict)
                            and field in example.response_body
                        ):
                            observed_values.append(example.response_body[field])
                if assertion.get("expected") not in observed_values and observed_values:
                    assertion["expected"] = observed_values[-1]
                    assertion["evidence"] = "Reviewed against the last matching value in the sanitized recording."
        workflow["approval"] = "pending"
        workflow["destructive"] = any(bool(step.get("destructive")) for step in reviewed_steps)
        if reviewed_steps and workflow["scenarios"]:
            reviewed_workflows.append(workflow)

    if not reviewed_workflows:
        raise ValueError("the reviewed fixture did not match any observed operations")
    assumptions = [
        *draft.assumptions,
        "The checked-in sample review duplicates the observed status GET for bounded polling and the observed final GET for business-state verification.",
    ]
    return service.edit_plan(
        draft.plan_id,
        PlanPatch(
            workflows=reviewed_workflows,
            assumptions=assumptions,
            uncertainties=[],
            supplied_test_data={},
        ),
        draft.revision,
    )


def approve_and_generate(
    service: OrchestratorService,
    plan: ReviewPlan,
    *,
    project_name: str,
    workflow_ids: list[str],
) -> dict[str, object]:
    selected = workflow_ids or [
        workflow.workflow_id for workflow in plan.workflows if workflow.approval != "rejected"
    ]
    approved = (
        plan
        if plan.is_approved and (not workflow_ids or set(workflow_ids) == {
            workflow.workflow_id for workflow in plan.workflows if workflow.approval == "approved"
        })
        else service.approve_plan(plan.plan_id, ApprovalRequest(workflow_ids=selected))
    )
    approved_path = ROOT / "generated" / f"{project_name}-approved-plan.json"
    write_json(approved_path, approved.model_dump(mode="json", by_alias=True))
    generation = service.generate(
        approved.recording_id,
        approved,
        project_name=project_name,
        explicit_approval=False,
        validate_project=False,
    )
    return {
        "recordingId": approved.recording_id,
        "planId": approved.plan_id,
        "approvedPlan": str(approved_path),
        "projectPath": generation.project_path,
        "generationReportId": generation.report_id,
        "generatedFileCount": len(generation.generated_files),
        "approvedWorkflowIds": selected,
        "status": "generated",
    }


def main() -> int:
    args = build_parser().parse_args()
    settings = Settings(
        db_path=ROOT / "orchestrator" / "data" / "webtest-agent.db",
        generated_root=ROOT / "generated",
        report_root=ROOT / "orchestrator" / "reports",
        generator_root=ROOT / "generator",
    )
    service = OrchestratorService(settings)

    if args.approve_plan_id:
        try:
            existing = service.get_plan(args.approve_plan_id)
            result = approve_and_generate(
                service,
                existing,
                project_name=args.project_name,
                workflow_ids=args.workflow_id,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"approval/generation failed: {exc}", file=sys.stderr)
            return 3
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    try:
        recording_payload = json.loads(args.recording.read_text(encoding="utf-8"))
        outcome = service.create_review(recording_from_wire(recording_payload))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"planning failed: {exc}", file=sys.stderr)
        return 2

    draft_path = ROOT / "generated" / f"{args.project_name}-draft-plan.json"
    write_json(draft_path, outcome.plan.model_dump(mode="json", by_alias=True))
    summary: dict[str, object] = {
        "recordingId": outcome.normalized.recording_id,
        "planId": outcome.plan.plan_id,
        "runId": outcome.run.run_id,
        "draftPlan": str(draft_path),
        "operationCount": len(outcome.normalized.operations),
        "filteredRequestCount": outcome.normalized.filtered_request_count,
        "workflowCount": len(outcome.plan.workflows),
        "scenarioCount": sum(len(workflow.scenarios) for workflow in outcome.plan.workflows),
        "warnings": outcome.warnings,
        "status": "awaiting-explicit-approval",
    }

    if not args.approve_fixture:
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(
            "No code was generated. Review the draft or open http://127.0.0.1:8000/review, "
            "then run with --approve-plan-id PLAN_ID. For the checked-in reviewed demo, use --approve-fixture."
        )
        return 0

    try:
        reviewed = apply_reviewed_fixture(service, outcome.plan, args.review_template)
        reviewed_path = ROOT / "generated" / f"{args.project_name}-reviewed-plan.json"
        write_json(reviewed_path, reviewed.model_dump(mode="json", by_alias=True))
        generation_summary = approve_and_generate(
            service,
            reviewed,
            project_name=args.project_name,
            workflow_ids=args.workflow_id,
        )
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"generation failed: {exc}", file=sys.stderr)
        return 3

    summary.update(
        generation_summary,
        reviewedPlan=str(reviewed_path),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
