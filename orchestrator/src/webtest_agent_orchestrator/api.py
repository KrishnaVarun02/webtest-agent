from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import ValidationError

from .adapters import (
    extension_action_from_canonical,
    extension_exploration_to_canonical,
    recording_from_wire,
)
from .config import PACKAGE_DIR, Settings
from .schemas import (
    ApprovalRequest,
    ExplorationRequest,
    ExtensionExplorationRequest,
    GenerateRequest,
    PlanPatch,
    ReviewPlan,
    ValidationRequest,
)
from .services import ApprovalRequiredError, NotFoundError, OrchestratorService


def _detail(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def create_app(settings: Settings | None = None, service: OrchestratorService | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = service or OrchestratorService(settings)
    app = FastAPI(
        title="WebTest Agent orchestrator",
        version="0.1.0",
        description="Local recording normalization, workflow planning, human review, generation, validation, and reporting.",
    )
    app.state.settings = settings
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_origin_regex=r"chrome-extension://[a-p]{32}",
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "If-Match"],
    )

    @app.middleware("http")
    async def security_headers(request: Any, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(NotFoundError)
    async def not_found(_: Any, exc: NotFoundError) -> Any:
        return __import__("fastapi.responses", fromlist=["JSONResponse"]).JSONResponse(
            status_code=404, content={"detail": _detail(exc)}
        )

    @app.exception_handler(ApprovalRequiredError)
    async def approval_required(_: Any, exc: ApprovalRequiredError) -> Any:
        return __import__("fastapi.responses", fromlist=["JSONResponse"]).JSONResponse(
            status_code=409, content={"detail": _detail(exc)}
        )

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "product": "WebTest Agent",
            "persistence": "sqlite",
            "llmProvider": service.provider.name,
            "llmAvailable": service.provider.available,
        }

    @app.get("/review", response_class=HTMLResponse)
    def review_ui() -> FileResponse:
        return FileResponse(PACKAGE_DIR / "static" / "review.html", media_type="text/html")

    @app.post("/api/v1/explore/next")
    def explore_next(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            if payload.get("schemaVersion") == "1.0.0":
                wire = ExtensionExplorationRequest.model_validate(payload)
                canonical, refs = extension_exploration_to_canonical(wire)
                return extension_action_from_canonical(service.next_action(canonical), refs)
            action = service.next_action(ExplorationRequest.model_validate(payload))
            return action.model_dump(mode="json", by_alias=True, exclude_none=True)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_detail(exc)) from exc

    @app.post("/api/v1/review")
    def create_review(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            recording = recording_from_wire(payload)
            outcome = service.create_review(recording)
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_detail(exc)) from exc
        return {
            "plan": outcome.plan.model_dump(mode="json", by_alias=True),
            "warnings": outcome.warnings,
            "recordingId": outcome.normalized.recording_id,
            "runId": outcome.run.run_id,
        }

    @app.post("/api/v1/recordings")
    def ingest_recording(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            outcome = service.create_review(recording_from_wire(payload))
        except (ValidationError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=_detail(exc)) from exc
        return {
            "recording": outcome.normalized.model_dump(mode="json", by_alias=True),
            "planId": outcome.plan.plan_id,
            "runId": outcome.run.run_id,
        }

    @app.get("/api/v1/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        return service.get_plan(plan_id).model_dump(mode="json", by_alias=True)

    @app.patch("/api/v1/plans/{plan_id}")
    def edit_plan(
        plan_id: str,
        patch: PlanPatch,
        revision: int | None = Query(default=None, ge=1),
        if_match: str | None = Header(default=None, alias="If-Match"),
    ) -> dict[str, Any]:
        try:
            expected = revision if revision is not None else int((if_match or "").strip('"'))
        except ValueError as exc:
            raise HTTPException(status_code=428, detail="A numeric revision query or If-Match header is required") from exc
        if expected is None:
            raise HTTPException(status_code=428, detail="A revision query or If-Match header is required")
        try:
            updated = service.edit_plan(plan_id, patch, expected)
        except ValueError as exc:
            if "revision conflict" in str(exc):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return updated.model_dump(mode="json", by_alias=True)

    @app.post("/api/v1/plans/{plan_id}/approve")
    def approve_plan(plan_id: str, request: ApprovalRequest) -> dict[str, Any]:
        try:
            plan = service.approve_plan(plan_id, request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return plan.model_dump(mode="json", by_alias=True)

    @app.post("/api/v1/plans/{plan_id}/reject")
    def reject_plan(plan_id: str) -> dict[str, Any]:
        return service.reject_plan(plan_id).model_dump(mode="json", by_alias=True)

    @app.post("/api/v1/generate")
    def generate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            raw_plan = payload.get("approvedPlan")
            if isinstance(raw_plan, dict) and set(raw_plan) == {"plan", "approved"}:
                raw_plan = raw_plan["plan"]
            if isinstance(raw_plan, dict):
                raw_plan = dict(raw_plan)
                raw_plan.pop("approved", None)
                plan = ReviewPlan.model_validate(raw_plan)
            elif payload.get("planId"):
                plan = service.get_plan(str(payload["planId"]))
            else:
                raise ValueError("approvedPlan or planId is required")
            request_payload = dict(payload)
            request_payload["approvedPlan"] = plan.model_dump(mode="json", by_alias=True)
            request = GenerateRequest.model_validate(request_payload)
            result = service.generate(
                request.recording_id,
                plan,
                project_name=request.project_name,
                explicit_approval=request.approved,
                validate_project=request.validate_project,
            )
        except ApprovalRequiredError:
            raise
        except (ValidationError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=422, detail=_detail(exc)) from exc
        report_path = None
        if result.report_id:
            report_record = service.repository.get_report(result.report_id)
            report_path = report_record[1] if report_record else None
        return {
            **result.model_dump(mode="json", by_alias=True),
            "runId": result.generation_id,
            "status": "completed",
            "reportPath": report_path,
        }

    @app.post("/api/v1/validate")
    def validate_project(request: ValidationRequest) -> dict[str, Any]:
        path = settings.generated_root / request.project_name
        result = service.validator.validate(
            path,
            run_tests=request.run_tests,
            max_repair_attempts=request.max_repair_attempts,
        )
        return result.model_dump(mode="json", by_alias=True)

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        return service.get_run(run_id).model_dump(mode="json", by_alias=True)

    @app.post("/api/v1/runs/{run_id}/resume")
    def resume_run(run_id: str) -> dict[str, Any]:
        try:
            return service.resume(run_id).model_dump(mode="json", by_alias=True)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/reports/{report_id}")
    def get_report(report_id: str) -> dict[str, Any]:
        value = service.repository.get_report(report_id)
        if not value:
            raise NotFoundError("report not found")
        report, path = value
        return {**report.model_dump(mode="json", by_alias=True), "htmlPath": path}

    @app.get("/api/v1/reports/{report_id}/html")
    def get_report_html(report_id: str) -> FileResponse:
        value = service.repository.get_report(report_id)
        if not value or not value[1] or not Path(value[1]).is_file():
            raise NotFoundError("HTML report not found")
        return FileResponse(value[1], media_type="text/html")

    return app


app = create_app()

