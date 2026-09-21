from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from .schemas import ExplorationAction, ExplorationRequest, InteractiveElement
from .security import canonical_origin, redact, url_origin


HIGH_RISK_WORDS = {
    "buy",
    "checkout",
    "delete",
    "pay",
    "purchase",
    "remove account",
    "upload",
    "upgrade role",
}
STATE_CHANGE_WORDS = {
    "add",
    "apply",
    "archive",
    "create",
    "save",
    "send",
    "submit",
    "update",
}


def _stop(reason: str) -> ExplorationAction:
    return ExplorationAction(action="stop", reason=reason)


def _is_forbidden(element: InteractiveElement) -> bool:
    label = f"{element.role} {element.name}".lower()
    return any(word in label for word in HIGH_RISK_WORDS)


def _needs_approval(element: InteractiveElement) -> bool:
    label = f"{element.role} {element.name}".lower()
    return element.likely_state_changing or any(word in label for word in STATE_CHANGE_WORDS)


class ExplorationAgent:
    """Deterministic policy guard and offline exploration strategy.

    An LLM may suggest a candidate in front of this component, but the returned
    action must still pass these guards. The offline strategy is intentionally
    conservative and never executes an action itself.
    """

    def next_action(self, request: ExplorationRequest) -> ExplorationAction:
        snapshot, policy = request.snapshot, request.policy
        try:
            current_origin = url_origin(snapshot.current_url)
            allowed = {canonical_origin(origin) for origin in policy.allowed_origins}
        except ValueError:
            return _stop("The current page or origin policy is invalid")
        if current_origin not in allowed:
            return _stop("The current page is outside the authorized origin list")
        if policy.actions_taken >= policy.max_actions:
            return _stop("The action budget is exhausted")
        if policy.elapsed_seconds >= policy.max_runtime_seconds:
            return _stop("The exploration runtime budget is exhausted")
        if (
            snapshot.state_fingerprint in policy.seen_state_fingerprints
            and policy.retries_for_state >= policy.max_retries_per_state
        ):
            return _stop("The page state repeated without useful progress")

        attempted = set(policy.attempted_element_refs)
        candidates = [element for element in snapshot.elements if element.enabled and element.ref not in attempted]
        for element in candidates:
            if _is_forbidden(element):
                continue
            role = element.role.lower()
            if role in {"textbox", "searchbox", "combobox"}:
                value = policy.test_data.get(element.ref) or policy.test_data.get(element.name)
                if value is None:
                    continue
                action_name = "select" if role == "combobox" and element.options else "fill"
                if action_name == "select" and value not in element.options:
                    continue
                return ExplorationAction(
                    action=action_name,
                    element_ref=element.ref,
                    value=str(redact(value, key=element.name)) if "password" in element.name.lower() else str(value),
                    requires_approval=_needs_approval(element) and element.ref not in policy.approved_element_refs,
                    reason="Uses user-supplied test data for an unvisited enabled control",
                )
            if role in {"button", "link", "menuitem", "tab", "checkbox", "radio"}:
                needs_approval = _needs_approval(element) and element.ref not in policy.approved_element_refs
                return ExplorationAction(
                    action="click",
                    element_ref=element.ref,
                    requires_approval=needs_approval,
                    reason=(
                        "The action may change server-side state and needs approval"
                        if needs_approval
                        else "Selects an enabled, unvisited interactive element"
                    ),
                )
        return _stop("No useful safe unvisited action remains")

    @staticmethod
    def validate_model_action(request: ExplorationRequest, action: ExplorationAction) -> ExplorationAction:
        """Enforce the same-origin/ref/risk boundary around a provider suggestion."""
        policy = request.policy
        snapshot = request.snapshot
        if action.action in {"click", "fill", "select"}:
            elements = {element.ref: element for element in snapshot.elements}
            if action.element_ref not in elements:
                return _stop("The suggested element reference was not present in the snapshot")
            element = elements[action.element_ref]
            if not element.enabled or _is_forbidden(element):
                return _stop("The suggested element is disabled or forbidden by policy")
            action.requires_approval = _needs_approval(element) and element.ref not in policy.approved_element_refs
        if action.action == "navigate":
            try:
                target = urljoin(snapshot.current_url, action.url or "")
                if url_origin(target) != url_origin(snapshot.current_url):
                    return _stop("Cross-origin navigation is not permitted")
                if url_origin(target) not in {canonical_origin(origin) for origin in policy.allowed_origins}:
                    return _stop("Navigation target is not authorized")
            except ValueError:
                return _stop("The suggested navigation URL is invalid")
            action.url = target
        return action

