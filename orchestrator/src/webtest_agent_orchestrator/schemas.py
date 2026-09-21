from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=True,
    )


class ActionKind(StrEnum):
    CLICK = "click"
    INPUT = "input"
    FILL = "fill"
    SELECT = "select"
    NAVIGATION = "navigation"
    SUBMIT = "submit"
    BACK = "back"
    WAIT = "wait"
    PAGE_CHANGE = "page_change"
    SCROLL = "scroll"


class LocatorCandidate(ApiModel):
    strategy: Literal["test_attribute", "role_name", "label", "id", "css"]
    value: str


class UIAction(ApiModel):
    id: str = Field(min_length=1, max_length=200)
    type: ActionKind
    timestamp: datetime
    page_url: str = ""
    element_ref: str | None = None
    locator_candidates: list[LocatorCandidate] = Field(default_factory=list)
    value: Any | None = None
    state_fingerprint: str | None = None
    state_changing: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class CapturedRequest(ApiModel):
    id: str = Field(default_factory=lambda: f"request-{uuid4().hex}")
    session_id: str | None = None
    method: str = Field(min_length=1, max_length=16)
    url: str = Field(min_length=1, max_length=16_384)
    normalized_path: str | None = None
    query_parameters: dict[str, Any] = Field(default_factory=dict)
    request_headers: dict[str, Any] = Field(default_factory=dict)
    request_content_type: str | None = None
    request_body: Any | None = None
    response_status: int | None = Field(default=None, ge=0, le=999)
    response_headers: dict[str, Any] = Field(default_factory=dict)
    response_body: Any | None = None
    page_url: str = ""
    timestamp: datetime
    timing: dict[str, float | int | None] = Field(default_factory=dict)
    related_ui_action_id: str | None = None
    resource_type: str = "fetch"
    excluded: bool = False

    @field_validator("method")
    @classmethod
    def uppercase_method(cls, value: str) -> str:
        return value.upper()

    @field_validator("timestamp")
    @classmethod
    def request_timestamp_is_aware(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class Recording(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, max_length=200)
    allowed_origins: list[str] = Field(min_length=1, max_length=50)
    started_at: datetime
    ended_at: datetime | None = None
    page_url: str = ""
    include_patterns: list[str] = Field(default_factory=list, max_length=100)
    exclude_patterns: list[str] = Field(default_factory=list, max_length=100)
    actions: list[UIAction] = Field(default_factory=list)
    requests: list[CapturedRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def recording_is_consistent(self) -> "Recording":
        if self.ended_at and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        action_ids = [action.id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action ids must be unique")
        request_ids = [request.id for request in self.requests]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("request ids must be unique")
        return self


class ParameterEvidence(ApiModel):
    name: str
    location: Literal["path", "query", "header", "body"] = "path"
    samples: list[Any] = Field(default_factory=list)
    value_type: str = "string"
    evidence: str


class OperationExample(ApiModel):
    request_id: str
    timestamp: datetime
    url: str
    query_parameters: dict[str, Any] = Field(default_factory=dict)
    request_headers: dict[str, Any] = Field(default_factory=dict)
    request_content_type: str | None = None
    request_body: Any | None = None
    response_status: int | None = None
    response_headers: dict[str, Any] = Field(default_factory=dict)
    response_body: Any | None = None
    related_ui_action_id: str | None = None
    page_url: str = ""


class NormalizedOperation(ApiModel):
    operation_id: str
    method: str
    origin: str
    normalized_path: str
    resource_pattern: str
    path_parameters: list[ParameterEvidence] = Field(default_factory=list)
    examples: list[OperationExample] = Field(default_factory=list)
    observed_statuses: list[int] = Field(default_factory=list)
    request_content_types: list[str] = Field(default_factory=list)
    response_content_types: list[str] = Field(default_factory=list)
    related_ui_action_ids: list[str] = Field(default_factory=list)
    auth_evidence: bool = False
    state_changing: bool = False
    asynchronous_evidence: bool = False
    response_schema: dict[str, Any] = Field(default_factory=dict)


class UnsupportedTraffic(ApiModel):
    request_id: str
    method: str
    sanitized_url: str
    reason: str


class ActionCorrelation(ApiModel):
    action_id: str
    operation_ids: list[str] = Field(default_factory=list)


class NormalizedRecording(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    recording_id: str
    session_id: str
    allowed_origins: list[str]
    operations: list[NormalizedOperation] = Field(default_factory=list)
    actions: list[UIAction] = Field(default_factory=list)
    correlations: list[ActionCorrelation] = Field(default_factory=list)
    pages_visited: list[str] = Field(default_factory=list)
    filtered_request_count: int = 0
    unsupported_traffic: list[UnsupportedTraffic] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DataDependency(ApiModel):
    source_step_id: str
    source_json_path: str
    target_step_id: str
    target_location: str
    variable_name: str
    confidence: Literal["high", "medium", "low"]
    evidence: str


class FlowStep(ApiModel):
    step_id: str
    operation_id: str
    name: str
    order: int = Field(ge=1)
    ui_action_ids: list[str] = Field(default_factory=list)
    dependencies: list[DataDependency] = Field(default_factory=list)
    extracts: dict[str, str] = Field(default_factory=dict)
    expected_statuses: list[int] = Field(default_factory=list)
    state_changing: bool = False
    destructive: bool = False
    asynchronous: bool = False
    review_notes: list[str] = Field(default_factory=list)

    @field_validator("extracts")
    @classmethod
    def extracts_are_structural_json_paths(cls, value: dict[str, str]) -> dict[str, str]:
        variable = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
        json_path = re.compile(
            r'^\$(?:(?:\.[A-Za-z_][A-Za-z0-9_]*)|(?:\[[0-9]+\])|(?:\["(?:[^"\\]|\\.)+"\]))*$'
        )
        for name, path in value.items():
            if not variable.fullmatch(name):
                raise ValueError(f"invalid extraction variable name: {name!r}")
            if len(path) > 512 or not json_path.fullmatch(path):
                raise ValueError(f"extraction {name!r} must be a structural JSONPath")
        return value


class AssertionSpec(ApiModel):
    kind: Literal["status", "content_type", "field_present", "field_type", "format", "value", "final_state"]
    path: str | None = None
    expected: Any | None = None
    evidence: str


class MutationSpec(ApiModel):
    location: Literal["path", "query", "header", "body"]
    path: str
    operation: Literal["remove", "replace", "omit_auth"]
    value: Any | None = None
    evidence: str


class ScenarioKind(StrEnum):
    POSITIVE = "positive"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    INVALID_TYPE = "invalid_type"
    INVALID_IDENTIFIER = "invalid_identifier"
    UNAUTHORIZED = "unauthorized"
    BOUNDARY = "boundary"
    ASYNCHRONOUS = "asynchronous"


class Scenario(ApiModel):
    scenario_id: str
    workflow_id: str
    name: str
    kind: ScenarioKind
    enabled: bool = True
    step_ids: list[str]
    mutation: MutationSpec | None = None
    expected_statuses: list[int] = Field(default_factory=list)
    assertions: list[AssertionSpec] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    uncertainty: str | None = None

    @model_validator(mode="after")
    def negative_has_at_most_one_mutation(self) -> "Scenario":
        if self.kind != ScenarioKind.POSITIVE and self.mutation is None and self.kind not in {
            ScenarioKind.ASYNCHRONOUS
        }:
            if self.enabled:
                raise ValueError("an enabled negative scenario must contain exactly one mutation")
        return self


class Workflow(ApiModel):
    workflow_id: str
    name: str
    steps: list[FlowStep]
    scenarios: list[Scenario] = Field(default_factory=list)
    approval: Literal["pending", "approved", "rejected"] = "pending"
    setup_step_ids: list[str] = Field(default_factory=list)
    cleanup_step_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    destructive: bool = False


class ReviewPlan(ApiModel):
    schema_version: Literal["1.0"] = "1.0"
    plan_id: str
    recording_id: str
    revision: int = Field(default=1, ge=1)
    status: Literal["draft", "approved", "rejected"] = "draft"
    workflows: list[Workflow]
    api_inventory: list[NormalizedOperation]
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    missing_test_data: list[str] = Field(default_factory=list)
    supplied_test_data: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_approved(self) -> bool:
        enabled_workflow_ids = {workflow.workflow_id for workflow in self.workflows if workflow.approval == "approved"}
        return self.status == "approved" and bool(enabled_workflow_ids)


class PlanPatch(ApiModel):
    workflows: list[Workflow] | None = None
    assumptions: list[str] | None = None
    uncertainties: list[str] | None = None
    supplied_test_data: dict[str, str] | None = None


class ApprovalRequest(ApiModel):
    workflow_ids: list[str] = Field(default_factory=list)
    note: str | None = None


class InteractiveElement(ApiModel):
    ref: str
    role: str
    name: str = ""
    enabled: bool = True
    value_type: str | None = None
    options: list[str] = Field(default_factory=list)
    likely_state_changing: bool = False


class ExplorationSnapshot(ApiModel):
    current_url: str
    page_title: str = ""
    headings: list[str] = Field(default_factory=list, max_length=100)
    elements: list[InteractiveElement] = Field(default_factory=list, max_length=500)
    visited_pages: list[str] = Field(default_factory=list, max_length=500)
    observed_apis: list[str] = Field(default_factory=list, max_length=1000)
    state_fingerprint: str


class ExplorationPolicy(ApiModel):
    allowed_origins: list[str] = Field(min_length=1)
    max_actions: int = Field(default=25, ge=1, le=200)
    max_runtime_seconds: int = Field(default=300, ge=1, le=3600)
    actions_taken: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)
    seen_state_fingerprints: list[str] = Field(default_factory=list, max_length=1000)
    attempted_element_refs: list[str] = Field(default_factory=list, max_length=2000)
    retries_for_state: int = Field(default=0, ge=0, le=10)
    max_retries_per_state: int = Field(default=2, ge=0, le=5)
    approved_element_refs: list[str] = Field(default_factory=list)
    test_data: dict[str, str] = Field(default_factory=dict)


class ExplorationRequest(ApiModel):
    snapshot: ExplorationSnapshot
    policy: ExplorationPolicy


class ExplorationAction(ApiModel):
    action: Literal["click", "fill", "select", "scroll", "wait", "back", "navigate", "stop"]
    element_ref: str | None = None
    value: str | None = None
    url: str | None = None
    requires_approval: bool = False
    reason: str

    @model_validator(mode="after")
    def valid_shape(self) -> "ExplorationAction":
        if self.action in {"click", "fill", "select"} and not self.element_ref:
            raise ValueError(f"{self.action} requires element_ref")
        if self.action == "navigate" and not self.url:
            raise ValueError("navigate requires url")
        if self.action == "stop" and any((self.element_ref, self.value, self.url)):
            raise ValueError("stop may not target an element or URL")
        return self


class ReviewRequest(ApiModel):
    recording: Recording


class GenerateRequest(ApiModel):
    recording_id: str
    approved: bool = False
    approved_plan: ReviewPlan | None = None
    plan_id: str | None = None
    project_name: str = Field(default="webtest-generated-tests", pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    validate_project: bool = False

    @model_validator(mode="after")
    def has_plan(self) -> "GenerateRequest":
        if self.approved_plan is None and self.plan_id is None:
            raise ValueError("approved_plan or plan_id is required")
        return self


# Wire schemas used by the Manifest V3 extension. These remain distinct from the
# canonical graph models so the persisted schema can evolve independently.
class ExtensionLocator(ApiModel):
    strategy: Literal["test-attribute", "role", "label", "id", "css"]
    value: str
    role: str | None = None
    name: str | None = None


class ExtensionAction(ApiModel):
    id: str
    session_id: str
    type: ActionKind
    timestamp: datetime
    page_url: str
    locator: ExtensionLocator | None = None
    value: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtensionCaptureConfiguration(ApiModel):
    allowed_origins: list[str] = Field(min_length=1)
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_operations: int = Field(ge=1, le=100_000)


class ExtensionHeader(ApiModel):
    name: str
    value: str


class ExtensionQueryParameter(ApiModel):
    name: str
    value: str


class ExtensionRecordedRequest(ApiModel):
    method: str
    url: str
    normalized_path: str
    query: list[ExtensionQueryParameter] = Field(default_factory=list)
    headers: list[ExtensionHeader] = Field(default_factory=list)
    content_type: str | None = None
    body: Any | None = None


class ExtensionRecordedResponse(ApiModel):
    status: int = Field(ge=0, le=999)
    status_text: str | None = None
    headers: list[ExtensionHeader] = Field(default_factory=list)
    content_type: str | None = None
    body: Any | None = None
    body_unavailable_reason: str | None = None


class ExtensionCapturedOperation(ApiModel):
    id: str
    session_id: str
    timestamp: datetime
    page_url: str
    resource_type: Literal["xhr", "fetch"]
    request: ExtensionRecordedRequest
    response: ExtensionRecordedResponse
    timing: dict[str, float | int | None]
    related_action_id: str | None = None
    included: bool
    exclusion_reason: Literal[
        "analytics", "telemetry", "static-resource", "advertisement", "third-party-tracking", "user-excluded"
    ] | None = None


class ExtensionRecordingMetadata(ApiModel):
    extension_version: Literal["0.1.0"]
    capture_scope: Literal["one-inspected-tab"]
    protocols: list[Literal["REST"]]
    formats: list[Literal["JSON", "form-urlencoded"]]
    reload_observed: bool


class ExtensionRecording(ApiModel):
    schema_version: Literal["1.0.0"]
    product: Literal["WebTest Agent"]
    session_id: str
    inspected_tab_id: int
    started_at: datetime
    ended_at: datetime | None = None
    configuration: ExtensionCaptureConfiguration
    actions: list[ExtensionAction] = Field(default_factory=list)
    operations: list[ExtensionCapturedOperation] = Field(default_factory=list)
    metadata: ExtensionRecordingMetadata


class ExtensionVisitedPage(ApiModel):
    url: str
    title: str
    visits: int = Field(ge=1)


class ExtensionObservedApi(ApiModel):
    method: str
    normalized_path: str
    status: int


class ExtensionSnapshotElement(ApiModel):
    ref: str
    role: str
    name: str
    enabled: bool


class ExtensionModelSnapshot(ApiModel):
    current_url: str
    title: str
    headings: list[str]
    interactive_elements: list[ExtensionSnapshotElement]
    visited_page_summary: list[ExtensionVisitedPage]
    observed_apis: list[ExtensionObservedApi]


class ExtensionExplorationLimits(ApiModel):
    max_actions: int = Field(ge=1, le=200)
    max_runtime_ms: int = Field(ge=1, le=3_600_000)
    max_retries: int = Field(ge=0, le=10)
    max_repeated_states: int = Field(ge=1, le=20)


class ExtensionAiAction(ApiModel):
    type: Literal["click", "fill", "select", "scroll", "wait", "back", "navigate", "stop"]
    element_ref: str | None = None
    value_ref: str | None = None
    direction: Literal["up", "down"] | None = None
    amount: int | None = Field(default=None, ge=1, le=1500)
    duration_ms: int | None = Field(default=None, ge=0, le=10_000)
    url: str | None = None
    reason: str | None = Field(default=None, max_length=300)


class ExtensionExplorationRequest(ApiModel):
    schema_version: Literal["1.0.0"]
    snapshot: ExtensionModelSnapshot
    history: list[ExtensionAiAction] = Field(default_factory=list)
    observed_apis: list[ExtensionObservedApi] = Field(default_factory=list)
    available_test_data_refs: list[str] = Field(default_factory=list)
    limits: ExtensionExplorationLimits


class GenerationResult(ApiModel):
    generation_id: str
    plan_id: str
    project_name: str
    project_path: str
    generated_files: list[str] = Field(default_factory=list)
    generator: str
    compile_result: dict[str, Any] = Field(default_factory=dict)
    test_result: dict[str, Any] = Field(default_factory=dict)
    report_id: str | None = None


class ValidationRequest(ApiModel):
    project_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
    run_tests: bool = True
    max_repair_attempts: int = Field(default=2, ge=0, le=2)


class ValidationResult(ApiModel):
    success: bool
    command: list[str]
    exit_code: int | None
    attempts: int
    elapsed_seconds: float
    sanitized_output: str
    timed_out: bool = False


class UICoverageAction(ApiModel):
    action_id: str
    action_type: str
    operation_ids: list[str] = Field(default_factory=list)


class UICoverageEntry(ApiModel):
    page_url: str
    actions: list[UICoverageAction] = Field(default_factory=list)


class EndpointExampleReport(ApiModel):
    request_id: str
    sanitized_url: str
    request_body: Any | None = None
    response_status: int | None = None
    response_body: Any | None = None
    related_ui_action_id: str | None = None


class ApiInventoryReportEntry(ApiModel):
    operation_id: str
    method: str
    origin: str
    normalized_path: str
    path_parameters: list[ParameterEvidence] = Field(default_factory=list)
    observed_statuses: list[int] = Field(default_factory=list)
    examples: list[EndpointExampleReport] = Field(default_factory=list)


class TestMatrixEntry(ApiModel):
    workflow_id: str
    workflow_name: str
    scenario_id: str
    scenario_name: str
    kind: ScenarioKind
    enabled: bool
    step_ids: list[str]
    expected_statuses: list[int] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)


class GenerationReport(ApiModel):
    report_id: str
    recording_id: str
    plan_id: str
    pages_visited: list[str]
    ui_actions_executed: int
    api_operations_observed: int
    normalized_endpoints: list[str]
    workflows_discovered: list[str]
    positive_scenarios_generated: int
    negative_scenarios_generated: int
    unsupported_operations: list[UnsupportedTraffic]
    unvisited_areas: list[str]
    generated_files: list[str]
    compile_result: dict[str, Any]
    test_results: dict[str, Any]
    failures_and_diagnostics: list[str]
    coverage_limitations: list[str]
    source_recording_ids: list[str]
    ui_coverage_map: list[UICoverageEntry] = Field(default_factory=list)
    api_inventory: list[ApiInventoryReportEntry] = Field(default_factory=list)
    test_matrix: list[TestMatrixEntry] = Field(default_factory=list)
    plan_assumptions: list[str] = Field(default_factory=list)
    plan_uncertainties: list[str] = Field(default_factory=list)
    data_dependencies: list[DataDependency] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphRun(ApiModel):
    run_id: str
    recording_id: str
    plan_id: str | None = None
    status: Literal["running", "awaiting_review", "approved", "generating", "completed", "failed"]
    current_node: str
    graph_backend: str
    state: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
