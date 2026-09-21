from __future__ import annotations

from webtest_agent_orchestrator.adapters import extension_exploration_to_canonical
from webtest_agent_orchestrator.exploration import ExplorationAgent
from webtest_agent_orchestrator.llm import provider_exploration_action
from webtest_agent_orchestrator.schemas import (
    ExplorationPolicy,
    ExplorationRequest,
    ExplorationSnapshot,
    ExtensionExplorationRequest,
    InteractiveElement,
)


def _request(**policy_updates):
    policy = ExplorationPolicy(
        allowed_origins=["https://app.example.test"],
        test_data={"field-user": "demo-user"},
    ).model_copy(update=policy_updates)
    return ExplorationRequest(
        snapshot=ExplorationSnapshot(
            current_url="https://app.example.test/page",
            elements=[InteractiveElement(ref="field-user", role="textbox", name="Username")],
            state_fingerprint="state-1",
        ),
        policy=policy,
    )


def test_exploration_respects_action_and_repeat_budgets() -> None:
    agent = ExplorationAgent()
    assert agent.next_action(_request(actions_taken=25)).action == "stop"
    repeated = _request(seen_state_fingerprints=["state-1"], retries_for_state=2)
    assert "repeated" in agent.next_action(repeated).reason.lower()


def test_exploration_uses_refs_and_requires_state_change_approval() -> None:
    request = _request()
    action = ExplorationAgent().next_action(request)
    assert action.action == "fill"
    assert action.element_ref == "field-user"
    request.snapshot.elements = [
        InteractiveElement(ref="save", role="button", name="Save changes", likely_state_changing=True)
    ]
    action = ExplorationAgent().next_action(request)
    assert action.action == "click"
    assert action.requires_approval


def test_exploration_refuses_prohibited_and_cross_origin_actions() -> None:
    request = _request()
    request.snapshot.elements = [InteractiveElement(ref="pay", role="button", name="Buy now")]
    assert ExplorationAgent().next_action(request).action == "stop"
    from webtest_agent_orchestrator.schemas import ExplorationAction

    model_action = ExplorationAction(action="navigate", url="https://evil.invalid", reason="try")
    assert ExplorationAgent.validate_model_action(request, model_action).action == "stop"


def test_extension_exploration_adapter_uses_local_value_reference() -> None:
    wire = ExtensionExplorationRequest.model_validate(
        {
            "schemaVersion": "1.0.0",
            "snapshot": {
                "currentUrl": "https://app.example.test/login",
                "title": "Login",
                "headings": ["Login"],
                "interactiveElements": [{"ref": "u1", "role": "textbox", "name": "Username", "enabled": True}],
                "visitedPageSummary": [],
                "observedApis": [],
            },
            "history": [],
            "observedApis": [],
            "availableTestDataRefs": ["TEST_USERNAME"],
            "limits": {"maxActions": 10, "maxRuntimeMs": 5000, "maxRetries": 2, "maxRepeatedStates": 2},
        }
    )
    canonical, refs = extension_exploration_to_canonical(wire)
    action = ExplorationAgent().next_action(canonical)
    assert action.value == "TEST_USERNAME"
    assert refs == {"u1": "TEST_USERNAME"}


def test_model_prompt_contains_references_but_not_test_data_values() -> None:
    class CapturingProvider:
        name = "capture"
        available = True

        def __init__(self):
            self.payload = None

        def complete_json(self, *, system, payload, schema):
            self.system = system
            self.payload = payload
            self.schema = schema
            return {
                "action": "stop",
                "elementRef": None,
                "value": None,
                "url": None,
                "requiresApproval": False,
                "reason": "done",
            }

    provider = CapturingProvider()
    request = _request()
    request.policy.test_data = {"TEST_PASSWORD": "seeded-model-secret"}
    request.snapshot.headings = [
        "password=PROMPT-PASSWORD-LEAK",
        "clientSecret=PROMPT-CLIENT-LEAK",
        "authorizationValue=PROMPT-AUTH-LEAK",
    ]
    action = provider_exploration_action(provider, request)
    assert action and action.action == "stop"
    assert "TEST_PASSWORD" in str(provider.payload)
    boundary = str((provider.system, provider.payload, provider.schema))
    for secret in (
        "seeded-model-secret",
        "PROMPT-PASSWORD-LEAK",
        "PROMPT-CLIENT-LEAK",
        "PROMPT-AUTH-LEAK",
    ):
        assert secret not in boundary
