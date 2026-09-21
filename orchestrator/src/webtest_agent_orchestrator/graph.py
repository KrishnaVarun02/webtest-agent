from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypedDict

from .normalization import CaptureNormalizer
from .planning import FlowPlanner, ScenarioDesigner
from .schemas import NormalizedRecording, Recording, ReviewPlan


class GraphState(TypedDict, total=False):
    run_id: str
    recording: dict[str, Any]
    normalized: dict[str, Any]
    plan: dict[str, Any]
    generation: dict[str, Any]
    validation: dict[str, Any]
    report: dict[str, Any]
    status: str
    current_node: str
    error: str


TransitionCallback = Callable[[str, GraphState], None]


try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - exercised in an explicit fallback test
    END = START = StateGraph = None  # type: ignore[assignment]


class PlanningGraph:
    """LangGraph pipeline with a deterministic fallback for constrained installs."""

    def __init__(
        self,
        normalizer: CaptureNormalizer,
        planner: FlowPlanner,
        designer: ScenarioDesigner,
        transition: TransitionCallback | None = None,
    ):
        self.normalizer = normalizer
        self.planner = planner
        self.designer = designer
        self.transition = transition
        self.backend_name = "langgraph" if StateGraph is not None else "deterministic-fallback"
        self._compiled: Any | None = None
        if StateGraph is not None:
            builder = StateGraph(GraphState)
            builder.add_node("capture_normalizer", self._capture_node)
            builder.add_node("flow_planning", self._flow_node)
            builder.add_node("scenario_design", self._scenario_node)
            builder.add_node("human_review", self._review_node)
            builder.add_edge(START, "capture_normalizer")
            builder.add_edge("capture_normalizer", "flow_planning")
            builder.add_edge("flow_planning", "scenario_design")
            builder.add_edge("scenario_design", "human_review")
            builder.add_edge("human_review", END)
            self._compiled = builder.compile()

    def _notify(self, node: str, state: GraphState) -> None:
        if self.transition:
            self.transition(node, state)

    def _capture_node(self, state: GraphState) -> GraphState:
        recording = Recording.model_validate(state["recording"])
        normalized = self.normalizer.normalize(recording)
        update: GraphState = {"normalized": normalized.model_dump(mode="json", by_alias=True), "current_node": "capture_normalizer"}
        self._notify("capture_normalizer", {**state, **update})
        return update

    def _flow_node(self, state: GraphState) -> GraphState:
        normalized = NormalizedRecording.model_validate(state["normalized"])
        plan = self.planner.plan(normalized)
        update: GraphState = {"plan": plan.model_dump(mode="json", by_alias=True), "current_node": "flow_planning"}
        self._notify("flow_planning", {**state, **update})
        return update

    def _scenario_node(self, state: GraphState) -> GraphState:
        plan = self.designer.design(ReviewPlan.model_validate(state["plan"]))
        update: GraphState = {"plan": plan.model_dump(mode="json", by_alias=True), "current_node": "scenario_design"}
        self._notify("scenario_design", {**state, **update})
        return update

    def _review_node(self, state: GraphState) -> GraphState:
        update: GraphState = {"status": "awaiting_review", "current_node": "human_review"}
        self._notify("human_review", {**state, **update})
        return update

    def invoke(self, state: GraphState) -> GraphState:
        if self._compiled is not None:
            return GraphState(self._compiled.invoke(state))
        current = dict(state)
        for node in (self._capture_node, self._flow_node, self._scenario_node, self._review_node):
            current.update(node(GraphState(current)))
        return GraphState(current)


NodeCallback = Callable[[GraphState], dict[str, Any]]


class GenerationGraph:
    def __init__(
        self,
        code_generation: NodeCallback,
        validation_and_repair: NodeCallback,
        report: NodeCallback,
        transition: TransitionCallback | None = None,
    ):
        self.callbacks = {
            "code_generation": code_generation,
            "validation_and_repair": validation_and_repair,
            "report": report,
        }
        self.transition = transition
        self.backend_name = "langgraph" if StateGraph is not None else "deterministic-fallback"
        self._compiled: Any | None = None
        if StateGraph is not None:
            builder = StateGraph(GraphState)
            builder.add_node("code_generation", lambda state: self._node("code_generation", state))
            builder.add_node("validation_and_repair", lambda state: self._node("validation_and_repair", state))
            builder.add_node("report", lambda state: self._node("report", state))
            builder.add_edge(START, "code_generation")
            builder.add_edge("code_generation", "validation_and_repair")
            builder.add_edge("validation_and_repair", "report")
            builder.add_edge("report", END)
            self._compiled = builder.compile()

    def _node(self, name: str, state: GraphState) -> GraphState:
        result = self.callbacks[name](state)
        update = GraphState({**result, "current_node": name})
        if name == "report":
            update["status"] = "completed"
        if self.transition:
            self.transition(name, {**state, **update})
        return update

    def invoke(self, state: GraphState, *, start_after: str | None = None) -> GraphState:
        # Full LangGraph invocation is the normal path. The explicit sequential
        # path also powers persisted resume from the first unfinished node.
        if start_after is None and self._compiled is not None:
            return GraphState(self._compiled.invoke(state))
        names = list(self.callbacks)
        start = names.index(start_after) + 1 if start_after in names else 0
        current = dict(state)
        for name in names[start:]:
            current.update(self._node(name, GraphState(current)))
        return GraphState(current)

