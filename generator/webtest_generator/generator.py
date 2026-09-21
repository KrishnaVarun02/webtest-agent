"""Deterministic, evidence-bound Java/TestNG project generation."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from . import templates


class GenerationError(ValueError):
    """Raised when an input plan is unsafe or not approved for generation."""


_PROJECT_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
_ENV_REFERENCE = re.compile(r"\$\{[A-Z][A-Z0-9_]*}\Z")
_PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][A-Za-z0-9_]*)}")
_UUID_VALUE = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![0-9a-f])"
)
_ISO_TIMESTAMP = re.compile(
    r"(?<!\d)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})(?!\d)"
)
_STRUCTURAL_IDENTIFIER_KEYS = {
    "actionid",
    "actionids",
    "cleanupstepids",
    "operationid",
    "planid",
    "recordingid",
    "relateduiactionid",
    "relateduiactionids",
    "requestid",
    "scenarioid",
    "setupstepids",
    "sourcestepid",
    "stepid",
    "targetstepid",
    "uiactionids",
    "workflowid",
}
_DYNAMIC_TIME_KEYS = {
    "timestamp",
    "createdat",
    "updatedat",
    "startedat",
    "endedat",
    "completedat",
    "deletedat",
    "expiresat",
    "processedat",
}
_COMPILE_DIAGNOSTIC_MARKERS = (
    "compilation error",
    "maven-compiler-plugin",
    "cannot find symbol",
    "illegal start of",
    "not a statement",
    "reached end of file while parsing",
    "should be declared in a file named",
    "package does not exist",
)
_RUNTIME_FAILURE_MARKERS = (
    "assertionerror",
    "conditiontimeoutexception",
    "polling timed out",
    "connection refused",
    "connectexception",
    "unknownhostexception",
    "sockettimeoutexception",
    "tests run:",
    "there are test failures",
    "failed tests:",
    "failed to execute goal org.apache.maven.plugins:maven-surefire-plugin",
    "failed to execute goal org.apache.maven.plugins:maven-failsafe-plugin",
)
_SENSITIVE_PARTS = (
    "token",
    "key",
    "secret",
    "password",
    "authorization",
    "credential",
    "cookie",
    "sessionid",
    "session_id",
    "set-cookie",
    "username",
)
_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "api-key",
}
_IGNORED_REQUEST_HEADERS = {
    "accept-encoding",
    "connection",
    "content-length",
    "host",
    "origin",
    "referer",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "user-agent",
}
_JAVA_RESERVED = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const",
    "continue", "default", "do", "double", "else", "enum", "extends", "final", "finally", "float",
    "for", "goto", "if", "implements", "import", "instanceof", "int", "interface", "long", "native",
    "new", "package", "private", "protected", "public", "return", "short", "static", "strictfp",
    "super", "switch", "synchronized", "this", "throw", "throws", "transient", "try", "void",
    "volatile", "while", "record", "sealed", "permits", "yield", "var",
}


def generate_project(plan: dict, output_root: Path, project_name: str) -> dict[str, Any]:
    """Generate an approved plan as a complete Maven project.

    The result is deterministic for the same plan and project name. Existing output
    for that exact project name is replaced only after a complete staging tree has
    been written successfully.
    """

    if not isinstance(plan, dict):
        raise GenerationError("plan must be a dictionary")
    _validate_project_name(project_name)
    approved_workflows = _approved_workflows(plan)
    sanitized_plan = _sanitize(copy.deepcopy(plan))
    approved_ids = {_string(_pick(workflow, "workflowId", "workflow_id")) for workflow in approved_workflows}
    sanitized_workflows = [
        workflow
        for workflow in _list(_pick(sanitized_plan, "workflows", default=[]))
        if _string(_pick(workflow, "workflowId", "workflow_id")) in approved_ids
    ]
    operations = {
        _string(_pick(operation, "operationId", "operation_id")): operation
        for operation in _list(_pick(sanitized_plan, "apiInventory", "api_inventory", "operations", default=[]))
    }
    if not operations:
        raise GenerationError("approved plan has no API inventory")

    files: dict[str, str] = {}
    files["pom.xml"] = templates.pom_xml(project_name)
    files["testng.xml"] = templates.TESTNG_XML
    files[".env.example"] = _env_example()
    files["README.md"] = _generated_readme(project_name)
    for filename, content in templates.FRAMEWORK_FILES.items():
        files[f"src/test/java/framework/{filename}"] = content
    files["src/test/java/generated/clients/GeneratedApiClient.java"] = templates.GENERATED_API_CLIENT_JAVA
    files["src/test/java/generated/listeners/WebTestReportListener.java"] = templates.REPORT_LISTENER_JAVA

    scenario_count = 0
    enabled_scenario_count = 0
    scenario_paths: list[str] = []
    for workflow in sorted(sanitized_workflows, key=_workflow_sort_key):
        source, total, enabled = _render_workflow_class(workflow, operations)
        class_name = _class_name(_string(_pick(workflow, "name", default="Workflow")), _string(_pick(workflow, "workflowId", "workflow_id")))
        path = f"src/test/java/generated/scenarios/{class_name}.java"
        files[path] = source
        scenario_paths.append(path)
        scenario_count += total
        enabled_scenario_count += enabled
    if not scenario_paths:
        raise GenerationError("approved plan has no approved workflows to generate")

    canonical_plan = _canonical_json(sanitized_plan)
    plan_digest = hashlib.sha256(canonical_plan.encode("utf-8")).hexdigest()
    files["src/test/resources/flows/approved-plan.json"] = canonical_plan + "\n"
    files["src/test/resources/recordings/source-recordings.json"] = _canonical_json(
        {
            "schemaVersion": "1.0",
            "recordingId": _pick(sanitized_plan, "recordingId", "recording_id", default="unknown"),
            "operations": list(operations.values()),
        }
    ) + "\n"
    files["src/test/resources/config/generation.json"] = _canonical_json(
        {
            "schemaVersion": "1.0",
            "planId": _pick(sanitized_plan, "planId", "plan_id", default="unknown"),
            "recordingId": _pick(sanitized_plan, "recordingId", "recording_id", default="unknown"),
            "projectName": project_name,
            "planSha256": plan_digest,
            "approvedWorkflowIds": sorted(approved_ids),
            "environmentOnlySecrets": True,
            "destructiveTestsDefaultEnabled": False,
        }
    ) + "\n"

    projected_paths = sorted([*files, "generation-report.json", "generation-manifest.json"])
    files["generation-report.json"] = _canonical_json(
        _generation_report(sanitized_plan, sanitized_workflows, operations, projected_paths)
    ) + "\n"

    manifest_entries = [
        {"path": path, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}
        for path, content in sorted(files.items())
    ]
    persisted_manifest = {
        "schemaVersion": "1.0",
        "projectName": project_name,
        "planSha256": plan_digest,
        "workflowCount": len(sanitized_workflows),
        "scenarioCount": scenario_count,
        "enabledScenarioCount": enabled_scenario_count,
        "files": manifest_entries,
    }
    files["generation-manifest.json"] = _canonical_json(persisted_manifest) + "\n"

    target = _write_atomically(files, Path(output_root), project_name)
    return {
        **persisted_manifest,
        "projectDirectory": str(target),
        "files": [*manifest_entries, {
            "path": "generation-manifest.json",
            "sha256": hashlib.sha256(files["generation-manifest.json"].encode("utf-8")).hexdigest(),
        }],
    }


def repair_project(*, project_path: Path, diagnostics: str, plan: dict | None) -> bool:
    """Restore recognized generated-source drift after a compilation failure.

    This hook deliberately cannot repair assertions, HTTP failures, timeouts, or
    other runtime behavior. It also refuses a changed plan or any unrecognized
    file in the generated tree. A successful repair is a byte-for-byte fresh
    generation from the same approved plan and uses the normal atomic writer.
    """

    supplied_project = Path(project_path).expanduser()
    if supplied_project.is_symlink():
        return False
    project = supplied_project.resolve()
    diagnostic_text = str(diagnostics or "").lower()
    if not project.is_dir() or project.is_symlink():
        return False
    if any(marker in diagnostic_text for marker in _RUNTIME_FAILURE_MARKERS):
        return False
    if not any(marker in diagnostic_text for marker in _COMPILE_DIAGNOSTIC_MARKERS):
        return False

    config_path = project / "src/test/resources/config/generation.json"
    manifest_path = project / "generation-manifest.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    project_name = _pick(config, "projectName", "project_name", default=None)
    stored_digest = _pick(config, "planSha256", "plan_sha256", default=None)
    if project_name != project.name or not isinstance(stored_digest, str):
        return False
    if (
        _pick(current_manifest, "projectName", "project_name", default=None) != project.name
        or _pick(current_manifest, "planSha256", "plan_sha256", default=None) != stored_digest
        or not isinstance(_pick(current_manifest, "files", default=None), list)
    ):
        return False

    candidate_plan: Any = plan
    if candidate_plan is None:
        try:
            candidate_plan = json.loads(
                (project / "src/test/resources/flows/approved-plan.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
    if not isinstance(candidate_plan, dict):
        return False
    try:
        _approved_workflows(candidate_plan)
    except GenerationError:
        return False
    candidate_digest = hashlib.sha256(
        _canonical_json(_sanitize(copy.deepcopy(candidate_plan))).encode("utf-8")
    ).hexdigest()
    if candidate_digest != stored_digest:
        return False

    # Generate the expected tree away from the project first. This recognizes
    # both hand-edited/missing generated files and projects emitted by an older
    # compatible generator, without touching the failing tree during diagnosis.
    try:
        with tempfile.TemporaryDirectory(prefix="webtest-repair-") as temporary:
            expected = Path(
                generate_project(candidate_plan, Path(temporary), project.name)["projectDirectory"]
            )
            expected_files = {
                path.relative_to(expected).as_posix(): path.read_bytes()
                for path in expected.rglob("*")
                if path.is_file()
            }
            current_files = {
                path.relative_to(project).as_posix(): path.read_bytes()
                for path in project.rglob("*")
                if path.is_file() and "target" not in path.relative_to(project).parts
            }
            unknown = set(current_files) - set(expected_files)
            if unknown:
                return False
            drifted = set(current_files) != set(expected_files) or any(
                current_files[path] != content
                for path, content in expected_files.items()
                if path in current_files
            )
            if not drifted:
                return False
    except (GenerationError, OSError):
        return False

    try:
        generate_project(candidate_plan, project.parent, project.name)
    except (GenerationError, OSError):
        return False
    return True


def _validate_project_name(project_name: str) -> None:
    if not isinstance(project_name, str) or not _PROJECT_NAME.fullmatch(project_name):
        raise GenerationError("project name must be 1-80 safe filename characters")
    if project_name in {".", ".."} or project_name.startswith("."):
        raise GenerationError("project name may not be hidden or traverse directories")


def _approved_workflows(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    status = str(_pick(plan, "status", default="")).lower()
    explicitly_approved = _pick(plan, "approved", default=False) is True
    if status != "approved" and not explicitly_approved:
        raise GenerationError("code generation requires plan status='approved'")
    workflows = _list(_pick(plan, "workflows", default=[]))
    approved = [
        workflow
        for workflow in workflows
        if isinstance(workflow, Mapping)
        and str(_pick(workflow, "approval", "status", default="pending")).lower() == "approved"
    ]
    if not approved:
        raise GenerationError("code generation requires at least one approved workflow")
    return approved


def _write_atomically(files: Mapping[str, str], output_root: Path, project_name: str) -> Path:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / project_name
    if target.is_symlink():
        raise GenerationError("refusing to replace a symlink project directory")
    stage = Path(tempfile.mkdtemp(prefix=f".{project_name}.stage-", dir=root))
    try:
        for relative, content in sorted(files.items()):
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        backup: Path | None = None
        if target.exists():
            if not target.is_dir():
                raise GenerationError("project output target exists and is not a directory")
            backup = Path(tempfile.mkdtemp(prefix=f".{project_name}.old-", dir=root))
            backup.rmdir()
            os.replace(target, backup)
        try:
            os.replace(stage, target)
        except Exception:
            if backup is not None and backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        if backup is not None:
            shutil.rmtree(backup)
        return target
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _render_workflow_class(
    workflow: Mapping[str, Any], operations: Mapping[str, Mapping[str, Any]]
) -> tuple[str, int, int]:
    workflow_id = _string(_pick(workflow, "workflowId", "workflow_id", default="workflow"))
    class_name = _class_name(_string(_pick(workflow, "name", default="Workflow")), workflow_id)
    steps = {
        _string(_pick(step, "stepId", "step_id")): step
        for step in _list(_pick(workflow, "steps", default=[]))
    }
    if not steps:
        raise GenerationError(f"approved workflow {workflow_id!r} has no steps")
    scenarios = sorted(_list(_pick(workflow, "scenarios", default=[])), key=_scenario_sort_key)
    if not scenarios:
        raise GenerationError(f"approved workflow {workflow_id!r} has no scenarios")
    token_variable = _find_token_variable(steps.values())
    methods: list[str] = []
    used_names: set[str] = set()
    enabled_count = 0
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            raise GenerationError(f"workflow {workflow_id!r} contains a non-object scenario")
        method_name = _method_name(
            _string(_pick(scenario, "name", default="scenario")),
            _string(_pick(scenario, "scenarioId", "scenario_id", default="scenario")),
        )
        if method_name in used_names:
            raise GenerationError(f"duplicate generated method name in workflow {workflow_id}: {method_name}")
        used_names.add(method_name)
        methods.append(_render_scenario_method(workflow, scenario, steps, operations, method_name, token_variable))
        if bool(_pick(scenario, "enabled", default=True)):
            enabled_count += 1

    token_literal = "null" if token_variable is None else _java_string(token_variable)
    source = f'''package generated.scenarios;

import framework.*;
import generated.clients.GeneratedApiClient;
import io.restassured.response.Response;
import java.time.Duration;
import java.util.List;
import java.util.Objects;
import generated.listeners.WebTestReportListener;
import org.testng.annotations.BeforeMethod;
import org.testng.annotations.Listeners;
import org.testng.annotations.Test;

/** Generated only from approved workflow { _java_doc(workflow_id) }. */
@Listeners(WebTestReportListener.class)
public final class {class_name} {{
    private Config config;
    private GeneratedApiClient client;

    @BeforeMethod(alwaysRun = true)
    public void configure() {{
        config = Config.fromEnvironment();
        client = new GeneratedApiClient(config);
    }}

    private AuthProvider configuredAuth(ScenarioContext context) {{
        return AuthProviders.fromEnvironment(config, context, {token_literal});
    }}

{_indent("\n\n".join(methods), 4)}
}}
'''
    return source, len(scenarios), enabled_count


def _render_scenario_method(
    workflow: Mapping[str, Any],
    scenario: Mapping[str, Any],
    all_steps: Mapping[str, Mapping[str, Any]],
    operations: Mapping[str, Mapping[str, Any]],
    method_name: str,
    token_variable: str | None,
) -> str:
    scenario_id = _string(_pick(scenario, "scenarioId", "scenario_id", default=method_name))
    step_ids = [_string(value) for value in _list(_pick(scenario, "stepIds", "step_ids", default=[]))]
    if not step_ids:
        raise GenerationError(f"scenario {scenario_id!r} has no steps")
    try:
        selected_steps = [all_steps[step_id] for step_id in step_ids]
    except KeyError as exception:
        raise GenerationError(f"scenario {scenario_id!r} references unknown step {exception.args[0]!r}") from exception
    included_ids = set(step_ids)
    for setup_id in _list(_pick(workflow, "setupStepIds", "setup_step_ids", default=[])):
        setup_id = _string(setup_id)
        if setup_id not in all_steps:
            raise GenerationError(f"workflow setup references unknown step {setup_id!r}")
        included_ids.add(setup_id)
    # Pull transitive producer steps into the same scenario so extracted values
    # cannot be referenced before they exist, even when a review UI selected only
    # the target operation.
    changed = True
    while changed:
        changed = False
        for selected_id in tuple(included_ids):
            for dependency in _list(_pick(all_steps[selected_id], "dependencies", default=[])):
                producer = _string(_pick(dependency, "sourceStepId", "source_step_id", default=""))
                if producer and producer not in all_steps:
                    raise GenerationError(f"step dependency references unknown producer {producer!r}")
                if producer and producer not in included_ids:
                    included_ids.add(producer)
                    changed = True
    ordered_steps = sorted((all_steps[value] for value in included_ids), key=_step_sort_key)

    operation_list: list[Mapping[str, Any]] = []
    for step in ordered_steps:
        operation_id = _string(_pick(step, "operationId", "operation_id"))
        if operation_id not in operations:
            raise GenerationError(f"scenario {scenario_id!r} references missing operation {operation_id!r}")
        operation_list.append(operations[operation_id])

    mutation = _pick(scenario, "mutation", default=None)
    kind = _string(_pick(scenario, "kind", default="positive")).lower()
    mutation_target = _mutation_target(mutation, kind, ordered_steps, operation_list) if mutation else None
    if kind not in {"positive", "asynchronous"} and bool(_pick(scenario, "enabled", default=True)) and mutation is None:
        raise GenerationError(f"enabled negative scenario {scenario_id!r} must mutate exactly one known-valid request")

    assertion_targets = _assertion_targets(scenario, operation_list, len(ordered_steps), mutation_target)
    groups = _scenario_groups(workflow, scenario, ordered_steps)
    enabled = bool(_pick(scenario, "enabled", default=True))
    annotation = f'@Test(groups = {{{", ".join(_java_string(group) for group in groups)}}}, enabled = {str(enabled).lower()})'
    lines = [annotation, f"public void {method_name}() {{", "    ScenarioContext context = new ScenarioContext();"]
    if kind not in {"positive", "asynchronous"}:
        lines.append("    config.requireNegativeTestEnvironment();")
    if "destructive" in groups:
        lines.append("    config.requireDestructiveOptIn();")
    for note in _list(_pick(scenario, "reviewNotes", "review_notes", default=[])):
        lines.append(f"    ExecutionTrace.note({_java_string('Review note: ' + str(note))});")
    uncertainty = _pick(scenario, "uncertainty", default=None)
    if uncertainty:
        lines.append(f"    ExecutionTrace.note({_java_string('Uncertainty: ' + str(uncertainty))});")

    for index, (step, operation) in enumerate(zip(ordered_steps, operation_list)):
        lines.extend(_render_step(
            scenario=scenario,
            step=step,
            operation=operation,
            index=index,
            step_count=len(ordered_steps),
            mutation=mutation if mutation_target == index else None,
            kind=kind,
            assertion_indexes=assertion_targets.get(index, []),
            token_variable=token_variable,
        ))
    lines.append("}")
    return "\n".join(lines)


def _render_step(
    *,
    scenario: Mapping[str, Any],
    step: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
    step_count: int,
    mutation: Any,
    kind: str,
    assertion_indexes: list[int],
    token_variable: str | None,
) -> list[str]:
    number = index + 1
    step_name = _string(_pick(step, "name", default=f"Step {number}"))
    method = _string(_pick(operation, "method", default="GET")).upper()
    path = _path_for_step(_string(_pick(operation, "normalizedPath", "normalized_path", default="/")), step)
    expected_status = _expected_status(scenario, step, operation, index, step_count, mutation is not None)
    example = _first_example(operation, None if mutation else expected_status)
    headers = _safe_request_headers(_mapping(_pick(example, "requestHeaders", "request_headers", "headers", default={})))
    query = copy.deepcopy(_mapping(_pick(example, "queryParameters", "query_parameters", "query", default={})))
    body = copy.deepcopy(_pick(example, "requestBody", "request_body", "body", default=None))
    query, body = _apply_request_dependencies(step, query, body)
    auth_override = False
    mutation_prelude: list[str] = []
    if mutation:
        location = _string(_pick(mutation, "location", default="")).lower()
        mutation_path = _string(_pick(mutation, "path", default=""))
        operation_name = _string(_pick(mutation, "operation", default="replace")).lower()
        value = _pick(mutation, "value", default=None)
        if location == "body":
            body = _mutate_json(body, mutation_path, operation_name, value)
        elif location == "query":
            _mutate_mapping(query, mutation_path, operation_name, value)
        elif location == "header":
            _mutate_mapping(headers, mutation_path, operation_name, value, case_insensitive=True)
            if operation_name == "omit_auth" or mutation_path.lower() in _SENSITIVE_HEADERS:
                auth_override = True
        elif location == "path":
            placeholder = mutation_path.removeprefix("$.").strip("{}")
            if kind == "invalid_identifier":
                mutation_prelude.append(f'context.put({_java_string(placeholder)}, TestDataFactory.nonexistentUuid());')
            elif operation_name == "replace":
                if value is None:
                    raise GenerationError("path replacement mutation requires a value")
                path = path.replace("${" + placeholder + "}", str(value))
            elif operation_name == "remove":
                path = path.replace("/${" + placeholder + "}", "")
            else:
                raise GenerationError(f"unsupported path mutation operation: {operation_name}")
        else:
            raise GenerationError(f"unsupported mutation location: {location}")

    content_type = _pick(example, "requestContentType", "request_content_type", default=None)
    if not content_type:
        content_types = _list(_pick(operation, "requestContentTypes", "request_content_types", default=[]))
        content_type = content_types[0] if content_types else "application/json"

    lines = ["", f"    // {number}. {_java_line_comment(step_name)}"]
    lines.extend(f"    {line}" for line in mutation_prelude)
    lines.append(f"    RequestDefinition.Builder request{number}Builder = RequestDefinition.builder({_java_string(method)}, {_java_string(path)});")
    for name, value in sorted(headers.items(), key=lambda item: str(item[0]).lower()):
        lines.append(f"    request{number}Builder.header({_java_string(str(name))}, {_java_string(str(value))});")
    for name, value in sorted(query.items(), key=lambda item: str(item[0])):
        lines.append(
            f"    request{number}Builder.query({_java_string(str(name))}, "
            f"TestDataFactory.value({_java_string(_compact_json(value))}));"
        )
    if content_type:
        lines.append(f"    request{number}Builder.contentType({_java_string(str(content_type))});")
    if body is not None:
        lines.append(f"    request{number}Builder.body(TestDataFactory.json({_java_string(_compact_json(body))}));")
    lines.append(f"    RequestDefinition request{number} = request{number}Builder.build();")

    auth_evidence = bool(_pick(operation, "authEvidence", "auth_evidence", default=False))
    if auth_override or kind == "unauthorized" and mutation is not None:
        auth_expression = "new NoAuthProvider()"
    elif auth_evidence:
        auth_expression = "configuredAuth(context)"
    else:
        auth_expression = "new NoAuthProvider()"
    lines.append(f"    AuthProvider auth{number} = {auth_expression};")

    assertions = _list(_pick(scenario, "assertions", default=[]))
    target_assertions = [assertions[value] for value in assertion_indexes]
    polling_assertion = _polling_assertion(step, operation, target_assertions)
    if polling_assertion is not None:
        poll_path, poll_expected = polling_assertion
        expected_expression = f"context.resolveObject(TestDataFactory.value({_java_string(_compact_json(poll_expected))}))"
        lines.extend([
            f"    Response response{number} = PollingUtility.poll({_java_string(step_name)},",
            f"            () -> client.execute({_java_string(step_name)}, request{number}, context, auth{number}),",
            f"            candidate -> Objects.equals(candidate.jsonPath().get({_java_string(_normalize_json_path(poll_path))}), {expected_expression}),",
            "            Duration.ofSeconds(config.pollTimeoutSeconds()),",
            "            Duration.ofMillis(config.pollIntervalMillis()));",
        ])
    else:
        lines.append(
            f"    Response response{number} = client.execute({_java_string(step_name)}, request{number}, context, auth{number});"
        )

    if expected_status is None:
        lines.append(f"    ExecutionTrace.note({_java_string('No approved HTTP status assertion for ' + step_name)});")
    else:
        lines.append(f"    AssertionUtility.assertStatus(response{number}, {expected_status});")

    response_content_types = _list(_pick(operation, "responseContentTypes", "response_content_types", default=[]))
    if response_content_types and expected_status != 204:
        lines.append(f"    AssertionUtility.assertContentType(response{number}, {_java_string(str(response_content_types[0]).split(';')[0])});")
    required_fields = _required_response_fields(operation)
    if required_fields and expected_status is not None and 200 <= expected_status < 300:
        fields = ", ".join(_java_string(field) for field in required_fields)
        lines.append(f"    AssertionUtility.assertRequiredFields(response{number}, List.of({fields}));")

    if expected_status is None or expected_status < 400:
        for variable, json_path in sorted(_mapping(_pick(step, "extracts", default={})).items()):
            lines.append(
                f"    DynamicValueExtractor.extract(response{number}, {_java_string(str(json_path))}, context, {_java_string(str(variable))});"
            )
    for assertion in target_assertions:
        lines.extend(f"    {line}" for line in _render_assertion(assertion, number, polling_assertion))
    for note in _list(_pick(step, "reviewNotes", "review_notes", default=[])):
        lines.append(f"    ExecutionTrace.note({_java_string('Step review note: ' + str(note))});")
    return lines


def _render_assertion(assertion: Mapping[str, Any], response_number: int, polling_assertion: tuple[str, Any] | None) -> list[str]:
    kind = _string(_pick(assertion, "kind", default="")).lower()
    path = _pick(assertion, "path", default=None)
    expected = _pick(assertion, "expected", default=None)
    response = f"response{response_number}"
    if kind == "status" and isinstance(expected, int):
        return [f"AssertionUtility.assertStatus({response}, {expected});"]
    if kind == "content_type" and isinstance(expected, str):
        return [f"AssertionUtility.assertContentType({response}, {_java_string(str(expected))});"]
    if kind in {"status", "content_type"} and isinstance(expected, list):
        # Flow planners often flatten per-operation assertions into one scenario.
        # Step-level expected statuses/content types are already emitted at the
        # operation that supplied the evidence, so replaying this flattened list
        # against the final response would be incorrect.
        return [f"ExecutionTrace.note({_java_string('Covered by the operation-level approved ' + kind + ' assertion')});"]
    if kind == "field_present" and path:
        return [f"AssertionUtility.assertFieldPresent({response}, {_java_string(str(path))});"]
    if kind == "field_type" and path and expected is not None:
        return [f"AssertionUtility.assertJsonType({response}, {_java_string(str(path))}, {_java_string(str(expected))});"]
    if kind == "format" and path and expected is not None:
        return [f"AssertionUtility.assertFormat({response}, {_java_string(str(path))}, {_java_string(str(expected))});"]
    if kind in {"value", "final_state"} and path and expected is not None:
        if _is_sensitive_name(str(path)) or _is_dynamic_name(str(path)):
            return [
                f"AssertionUtility.assertFieldPresent({response}, {_java_string(str(path))});",
                f"ExecutionTrace.note({_java_string('Exact comparison suppressed for a sensitive or dynamic field')});",
            ]
        # Polling already waits for this value, but retain an explicit final assertion.
        return [
            f"AssertionUtility.assertJsonPathEquals({response}, {_java_string(str(path))}, "
            f"context.resolveObject(TestDataFactory.value({_java_string(_compact_json(expected))})));"
        ]
    evidence = _string(_pick(assertion, "evidence", default="approved plan"))
    return [f"ExecutionTrace.note({_java_string('Unsupported approved assertion (' + kind + '): ' + evidence)});"]


def _polling_assertion(
    step: Mapping[str, Any], operation: Mapping[str, Any], assertions: list[Mapping[str, Any]]
) -> tuple[str, Any] | None:
    asynchronous = bool(_pick(step, "asynchronous", default=False)) or bool(
        _pick(operation, "asynchronousEvidence", "asynchronous_evidence", default=False)
    )
    if not asynchronous or _string(_pick(operation, "method", default="GET")).upper() != "GET":
        return None
    for assertion in assertions:
        if _string(_pick(assertion, "kind", default="")).lower() in {"value", "final_state"}:
            path = _pick(assertion, "path", default=None)
            expected = _pick(assertion, "expected", default=None)
            if (
                path
                and expected is not None
                and not _is_sensitive_name(str(path))
                and not _is_dynamic_name(str(path))
            ):
                return str(path), expected
    return None


def _assertion_targets(
    scenario: Mapping[str, Any], operations: list[Mapping[str, Any]], step_count: int, mutation_target: int | None
) -> dict[int, list[int]]:
    targets: dict[int, list[int]] = {}
    for assertion_index, assertion in enumerate(_list(_pick(scenario, "assertions", default=[]))):
        kind = _string(_pick(assertion, "kind", default="")).lower()
        expected = _pick(assertion, "expected", default=None)
        path = _pick(assertion, "path", default=None)
        target = step_count - 1
        if kind == "status" and mutation_target is not None:
            target = mutation_target
        elif path and kind in {"field_present", "field_type", "format"}:
            matches = []
            for index, operation in enumerate(operations):
                for example in _examples(operation):
                    status = _pick(example, "responseStatus", "response_status", default=None)
                    if isinstance(status, int) and status >= 400:
                        continue
                    body = _pick(example, "responseBody", "response_body", default=None)
                    if _json_path_lookup(body, str(path))[0]:
                        matches.append(index)
                        break
            if matches:
                target = matches[-1]
        elif path and expected is not None:
            matches: list[int] = []
            for index, operation in enumerate(operations):
                for example in _examples(operation):
                    body = _pick(example, "responseBody", "response_body", default=None)
                    found, value = _json_path_lookup(body, str(path))
                    if found and value == expected:
                        matches.append(index)
                        break
            if matches:
                target = matches[-1]
        targets.setdefault(target, []).append(assertion_index)
    return targets


def _mutation_target(
    mutation: Any,
    kind: str,
    steps: list[Mapping[str, Any]],
    operations: list[Mapping[str, Any]],
) -> int:
    if not isinstance(mutation, Mapping):
        raise GenerationError("scenario mutation must be an object")
    location = _string(_pick(mutation, "location", default="")).lower()
    path = _string(_pick(mutation, "path", default="")).removeprefix("$.").strip("{}")
    explicit_operation = _pick(mutation, "operationId", "operation_id", default=None)
    if explicit_operation:
        for index, step in enumerate(steps):
            if _pick(step, "operationId", "operation_id") == explicit_operation:
                return index
        raise GenerationError(f"mutation references operation not present in scenario: {explicit_operation}")
    for index, operation in enumerate(operations):
        example = _first_example(operation)
        if location == "body" and _json_path_lookup(_pick(example, "requestBody", "request_body", default=None), path)[0]:
            return index
        if location == "query" and _mapping(_pick(example, "queryParameters", "query_parameters", default={})).get(path) is not None:
            return index
        if location == "header":
            if kind == "unauthorized" and bool(_pick(operation, "authEvidence", "auth_evidence", default=False)):
                return index
            headers = _mapping(_pick(example, "requestHeaders", "request_headers", default={}))
            if any(str(key).lower() == path.lower() for key in headers):
                return index
        if location == "path" and ("{" + path + "}") in _string(_pick(operation, "normalizedPath", "normalized_path", default="")):
            return index
    if kind == "unauthorized":
        for index, operation in enumerate(operations):
            if bool(_pick(operation, "authEvidence", "auth_evidence", default=False)):
                return index
    raise GenerationError(f"mutation path {path!r} was not found in a known-valid {location} request")


def _mutate_json(body: Any, path: str, operation: str, value: Any) -> Any:
    if not isinstance(body, dict):
        raise GenerationError("body mutation requires an observed JSON object body")
    result = copy.deepcopy(body)
    normalized = path.removeprefix("$.")
    parts = [part for part in normalized.split(".") if part]
    if not parts:
        raise GenerationError("body mutation path is empty")
    current: Any = result
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise GenerationError(f"body mutation path does not exist: {path}")
        current = current[part]
    leaf = parts[-1]
    if not isinstance(current, dict) or leaf not in current:
        raise GenerationError(f"body mutation path does not exist: {path}")
    if operation == "remove":
        del current[leaf]
    elif operation == "replace":
        current[leaf] = value
    else:
        raise GenerationError(f"unsupported body mutation operation: {operation}")
    return result


def _mutate_mapping(
    values: dict[str, Any], path: str, operation: str, value: Any, *, case_insensitive: bool = False
) -> None:
    key = path.removeprefix("$.")
    if case_insensitive:
        match = next((candidate for candidate in values if str(candidate).lower() == key.lower()), key)
    else:
        match = key
    if operation in {"remove", "omit_auth"}:
        values.pop(match, None)
    elif operation == "replace":
        values[match] = value
    else:
        raise GenerationError(f"unsupported mapping mutation operation: {operation}")


def _expected_status(
    scenario: Mapping[str, Any],
    step: Mapping[str, Any],
    operation: Mapping[str, Any],
    index: int,
    step_count: int,
    is_mutated_step: bool,
) -> int | None:
    scenario_statuses = [value for value in _list(_pick(scenario, "expectedStatuses", "expected_statuses", default=[])) if isinstance(value, int)]
    explicit_step_ids = [_string(value) for value in _list(_pick(scenario, "stepIds", "step_ids", default=[]))]
    current_step_id = _string(_pick(step, "stepId", "step_id"))
    if len(scenario_statuses) == len(explicit_step_ids) and current_step_id in explicit_step_ids:
        return scenario_statuses[explicit_step_ids.index(current_step_id)]
    if scenario_statuses and is_mutated_step:
        return scenario_statuses[-1]
    if len(scenario_statuses) == 1 and index == step_count - 1:
        return scenario_statuses[0]
    step_statuses = [value for value in _list(_pick(step, "expectedStatuses", "expected_statuses", default=[])) if isinstance(value, int)]
    if step_statuses:
        return step_statuses[0]
    observed = [value for value in _list(_pick(operation, "observedStatuses", "observed_statuses", default=[])) if isinstance(value, int)]
    if observed:
        successful = [value for value in observed if 200 <= value < 400]
        return successful[0] if successful else observed[0]
    return None


def _required_response_fields(operation: Mapping[str, Any]) -> list[str]:
    schema = _mapping(_pick(operation, "responseSchema", "response_schema", default={}))
    required = _list(_pick(schema, "required", default=[]))
    return sorted({str(value) for value in required if isinstance(value, str) and value})


def _path_for_step(path: str, step: Mapping[str, Any]) -> str:
    dependencies = _list(_pick(step, "dependencies", default=[]))
    path_dependencies = [
        dependency for dependency in dependencies
        if _string(_pick(dependency, "targetLocation", "target_location", default="")).lower().startswith("path")
    ]
    placeholders = _PLACEHOLDER.findall(path)
    for dependency in path_dependencies:
        variable = _string(_pick(dependency, "variableName", "variable_name", default=""))
        target_location = _string(_pick(dependency, "targetLocation", "target_location", default="")).lower()
        if not variable:
            continue
        indexed = re.fullmatch(r"path\[(\d+)]", target_location)
        if indexed:
            segments = path.split("/")
            # target indexes were derived from path.strip('/').split('/'); the
            # leading empty element in an absolute path shifts by one here.
            segment_index = int(indexed.group(1)) + (1 if path.startswith("/") else 0)
            if segment_index < len(segments) and _PLACEHOLDER.search(segments[segment_index]):
                segments[segment_index] = "${" + variable + "}"
                path = "/".join(segments)
                placeholders = _PLACEHOLDER.findall(path)
                continue
        if variable in placeholders:
            path = path.replace("{" + variable + "}", "${" + variable + "}")
        elif len(placeholders) == 1:
            path = path.replace("{" + placeholders[0] + "}", "${" + variable + "}")
    return _PLACEHOLDER.sub(lambda match: "${" + match.group(1) + "}", path)


def _apply_request_dependencies(
    step: Mapping[str, Any], query: dict[str, Any], body: Any
) -> tuple[dict[str, Any], Any]:
    query_copy = copy.deepcopy(query)
    body_copy = copy.deepcopy(body)
    for dependency in _list(_pick(step, "dependencies", default=[])):
        location = _string(_pick(dependency, "targetLocation", "target_location", default=""))
        variable = _string(_pick(dependency, "variableName", "variable_name", default=""))
        if not variable:
            continue
        replacement = "${" + variable + "}"
        lowered = location.lower()
        if lowered.startswith("query:"):
            _replace_dependency_value(query_copy, location.split(":", 1)[1], replacement)
        elif lowered.startswith("body:"):
            _replace_dependency_value(body_copy, location.split(":", 1)[1], replacement)
    return query_copy, body_copy


def _replace_dependency_value(container: Any, path: str, replacement: str) -> None:
    if container is None:
        return
    normalized = path.removeprefix("$.").removeprefix("$")
    parts = [part for part in re.split(r"\.|\[|\]", normalized) if part]
    if not parts:
        return
    current = container
    for part in parts[:-1]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return
    leaf = parts[-1]
    if isinstance(current, dict) and leaf in current:
        current[leaf] = replacement
    elif isinstance(current, list) and leaf.isdigit() and int(leaf) < len(current):
        current[int(leaf)] = replacement


def _examples(operation: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    examples = [value for value in _list(_pick(operation, "examples", default=[])) if isinstance(value, Mapping)]
    return sorted(
        examples,
        key=lambda value: (
            _string(_pick(value, "timestamp", default="")),
            _string(_pick(value, "requestId", "request_id", default="")),
        ),
    )


def _first_example(operation: Mapping[str, Any], expected_status: int | None = None) -> Mapping[str, Any]:
    examples = _examples(operation)
    if not examples:
        return {}
    if expected_status is not None:
        matching = [
            example for example in examples
            if _pick(example, "responseStatus", "response_status", default=None) == expected_status
        ]
        if matching:
            return matching[0]
    successful = [
        example for example in examples
        if isinstance(_pick(example, "responseStatus", "response_status", default=None), int)
        and 200 <= _pick(example, "responseStatus", "response_status") < 400
    ]
    return successful[0] if successful else examples[0]


def _find_token_variable(steps: Iterable[Mapping[str, Any]]) -> str | None:
    candidates: list[str] = []
    for step in steps:
        for variable, json_path in _mapping(_pick(step, "extracts", default={})).items():
            combined = (str(variable) + " " + str(json_path)).lower()
            if "token" in combined:
                candidates.append(str(variable))
    return sorted(candidates)[0] if candidates else None


def _scenario_groups(
    workflow: Mapping[str, Any], scenario: Mapping[str, Any], steps: list[Mapping[str, Any]]
) -> list[str]:
    kind = _string(_pick(scenario, "kind", default="positive")).lower()
    requested = {_safe_group(str(group)) for group in _list(_pick(scenario, "groups", default=[])) if str(group).strip()}
    requested.add("regression")
    requested.add("positive" if kind == "positive" else "negative")
    if kind == "asynchronous" or any(bool(_pick(step, "asynchronous", default=False)) for step in steps):
        requested.add("asynchronous")
        if kind == "asynchronous":
            requested.add("positive")
            requested.discard("negative")
    if "destructive" in requested or any(bool(_pick(step, "destructive", default=False)) for step in steps):
        requested.add("destructive")
    allowed_order = ["smoke", "regression", "positive", "negative", "asynchronous", "destructive"]
    ordered = [group for group in allowed_order if group in requested]
    ordered.extend(sorted(requested - set(allowed_order)))
    return ordered


def _safe_group(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower()).strip("-")
    return safe or "regression"


def _sanitize(value: Any, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        parent = (key or "").replace("_", "").lower()
        semantic_hint = " ".join(
            str(value.get(candidate, "")) for candidate in ("path", "name", "parameterName", "parameter_name")
        )
        semantic_secret = _is_sensitive_name(semantic_hint)
        semantic_dynamic = _is_dynamic_name(semantic_hint)
        assertion_kind = str(value.get("kind", "")).lower()
        for raw_name, child in value.items():
            name = str(raw_name)
            compact_name = name.replace("_", "").lower()
            # Extraction maps and JSON Schemas use field names as metadata. Their
            # values are paths/type declarations, not captured values.
            structural = parent in {"extracts", "responseschema", "requestschema", "properties"}
            if compact_name == "origin" and isinstance(child, str):
                clean[name] = "${WEBTEST_BASE_URL}"
            elif compact_name in {"url", "pageurl"} and isinstance(child, str):
                clean[name] = _environment_url(child)
            elif semantic_secret and compact_name in {"expected", "value", "samples", "default", "example"}:
                clean[name] = _environmentize(child, semantic_hint)
            elif (
                not structural
                and compact_name not in _STRUCTURAL_IDENTIFIER_KEYS
                and (
                    _is_dynamic_name(name)
                    or (
                        semantic_dynamic
                        and compact_name in {"expected", "value", "samples", "default", "example"}
                        and not (
                            compact_name == "expected"
                            and assertion_kind
                            in {"status", "content_type", "field_present", "field_type", "format"}
                        )
                    )
                )
            ):
                clean[name] = _dynamicize(child, semantic_hint or name)
            elif not structural and _is_sensitive_name(name) and not isinstance(child, Mapping):
                clean[name] = _environment_reference(name, child)
            else:
                clean[name] = _sanitize(child, name)
        return clean
    if isinstance(value, list):
        return [_sanitize(child, key) for child in value]
    if isinstance(value, tuple):
        return [_sanitize(child, key) for child in value]
    if isinstance(value, str):
        if _ENV_REFERENCE.fullmatch(value):
            return value
        value = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer ${API_TOKEN}", value)
        value = re.sub(
            r"(?i)((?:access|refresh)[_-]?token|password|secret|authorization|api[_-]?key)(\s*[=:]\s*)([^,;\s&]+)",
            lambda match: match.group(1) + match.group(2) + _environment_reference(match.group(1), match.group(3)),
            value,
        )
        compact_key = (key or "").replace("_", "").lower()
        if compact_key not in _STRUCTURAL_IDENTIFIER_KEYS:
            value = _replace_dynamic_literals(value)
        return value
    return value


def _environment_reference(name: str, value: Any) -> str:
    if isinstance(value, str) and _ENV_REFERENCE.fullmatch(value):
        return value
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if "username" in normalized:
        variable = "TEST_USERNAME"
    elif "password" in normalized:
        variable = "TEST_PASSWORD"
    elif "api" in normalized and "key" in normalized:
        variable = "API_KEY"
    elif "cookie" in normalized or "session" in normalized:
        variable = "TEST_COOKIE"
    elif "token" in normalized or "authorization" in normalized:
        variable = "API_TOKEN"
    elif "credential" in normalized:
        variable = "TEST_CREDENTIAL"
    else:
        variable = "TEST_SECRET"
    return "${" + variable + "}"


def _environmentize(value: Any, hint: str) -> Any:
    if isinstance(value, list):
        return [_environmentize(child, hint) for child in value]
    if isinstance(value, tuple):
        return [_environmentize(child, hint) for child in value]
    if isinstance(value, Mapping):
        return {str(name): _environmentize(child, str(name)) for name, child in value.items()}
    if value is None:
        return None
    return _environment_reference(hint, value)


def _dynamicize(value: Any, hint: str) -> Any:
    if isinstance(value, list):
        return [_dynamicize(child, hint) for child in value]
    if isinstance(value, tuple):
        return [_dynamicize(child, hint) for child in value]
    if isinstance(value, Mapping):
        return {str(name): _dynamicize(child, str(name)) for name, child in value.items()}
    if value is None:
        return None
    if isinstance(value, str) and _ENV_REFERENCE.fullmatch(value):
        return value
    return _dynamic_reference(hint)


def _dynamic_reference(name: str) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", name.lower())
    if compact in _DYNAMIC_TIME_KEYS or "timestamp" in compact:
        return "${RECORDED_TIMESTAMP}"
    words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", name.replace("-", "_"))
    variable = "_".join(word.upper() for word in words if word)
    if compact == "id" or not variable:
        variable = "RESOURCE_ID"
    elif not variable.endswith("_ID") and compact.endswith("id"):
        variable += "_ID"
    return "${" + variable + "}"


def _replace_dynamic_literals(value: str) -> str:
    value = _UUID_VALUE.sub("${RESOURCE_ID}", value)
    return _ISO_TIMESTAMP.sub("${RECORDED_TIMESTAMP}", value)


def _environment_url(value: str) -> str:
    if value.startswith("${WEBTEST_BASE_URL}"):
        suffix = value[len("${WEBTEST_BASE_URL}"):]
        suffix = suffix.split("?", 1)[0].split("#", 1)[0]
        return "${WEBTEST_BASE_URL}" + _sanitize_url_path(suffix or "/")
    try:
        parsed = urlsplit(value)
    except ValueError:
        return _replace_dynamic_literals(value)
    if parsed.scheme.lower() in {"http", "https"} and parsed.hostname:
        # Query parameters are persisted separately and recursively sanitized.
        return "${WEBTEST_BASE_URL}" + _sanitize_url_path(parsed.path or "/")
    return _replace_dynamic_literals(value)


def _sanitize_url_path(path: str) -> str:
    sanitized = _replace_dynamic_literals(path)
    segments = sanitized.split("/")
    for index, segment in enumerate(segments):
        if segment.isdigit():
            segments[index] = "${RESOURCE_ID}"
    return "/".join(segments)


def _is_sensitive_name(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    compact = lowered.replace("_", "")
    return any(part.replace("_", "") in compact for part in _SENSITIVE_PARTS)


def _is_dynamic_name(name: str) -> bool:
    lowered = name.lower().replace("-", "_")
    compact = re.sub(r"[^a-z0-9]+", "", lowered)
    if compact in _STRUCTURAL_IDENTIFIER_KEYS:
        return False
    if compact == "id" or compact.endswith("id"):
        return True
    return compact in _DYNAMIC_TIME_KEYS or "timestamp" in compact


def _safe_request_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    clean: dict[str, str] = {}
    for name, value in headers.items():
        lowered = str(name).lower()
        if lowered in _SENSITIVE_HEADERS or lowered in _IGNORED_REQUEST_HEADERS:
            continue
        if _is_sensitive_name(str(name)):
            continue
        clean[str(name)] = str(value)
    return clean


def _generation_report(
    plan: Mapping[str, Any],
    workflows: list[Mapping[str, Any]],
    operations: Mapping[str, Mapping[str, Any]],
    files: list[str],
) -> dict[str, Any]:
    scenarios = [
        (workflow, scenario)
        for workflow in workflows
        for scenario in _list(_pick(workflow, "scenarios", default=[]))
    ]
    action_operations: dict[str, set[str]] = {}
    page_actions: dict[str, set[str]] = {}
    endpoint_examples: list[dict[str, Any]] = []
    for operation_id, operation in sorted(operations.items()):
        operation_actions = {
            _string(action_id)
            for action_id in _list(_pick(operation, "relatedUiActionIds", "related_ui_action_ids", default=[]))
            if _string(action_id)
        }
        for example in _examples(operation):
            action_id = _string(_pick(example, "relatedUiActionId", "related_ui_action_id", default=""))
            page_url = _string(_pick(example, "pageUrl", "page_url", default=""))
            if action_id:
                operation_actions.add(action_id)
                if page_url:
                    page_actions.setdefault(page_url, set()).add(action_id)
            endpoint_examples.append(
                {
                    "operationId": operation_id,
                    "requestId": _pick(example, "requestId", "request_id", default=""),
                    "sanitizedUrl": _pick(example, "url", default=""),
                    "request": {
                        "queryParameters": _pick(
                            example, "queryParameters", "query_parameters", default={}
                        ),
                        "headers": _pick(example, "requestHeaders", "request_headers", default={}),
                        "contentType": _pick(
                            example, "requestContentType", "request_content_type", default=None
                        ),
                        "body": _pick(example, "requestBody", "request_body", default=None),
                    },
                    "response": {
                        "status": _pick(example, "responseStatus", "response_status", default=None),
                        "headers": _pick(example, "responseHeaders", "response_headers", default={}),
                        "body": _pick(example, "responseBody", "response_body", default=None),
                    },
                    "relatedUiActionId": action_id or None,
                    "pageUrl": page_url or None,
                }
            )
        for action_id in operation_actions:
            action_operations.setdefault(action_id, set()).add(operation_id)

    # Workflow step links are approved evidence too, and can remain useful when
    # an endpoint example did not retain a page association.
    data_dependencies: list[dict[str, Any]] = []
    for workflow in workflows:
        workflow_id = _string(_pick(workflow, "workflowId", "workflow_id", default=""))
        workflow_name = _string(_pick(workflow, "name", default=""))
        for step in _list(_pick(workflow, "steps", default=[])):
            operation_id = _string(_pick(step, "operationId", "operation_id", default=""))
            for action_id_value in _list(_pick(step, "uiActionIds", "ui_action_ids", default=[])):
                action_id = _string(action_id_value)
                if action_id:
                    action_operations.setdefault(action_id, set()).add(operation_id)
            for dependency in _list(_pick(step, "dependencies", default=[])):
                if not isinstance(dependency, Mapping):
                    continue
                data_dependencies.append(
                    {
                        "workflowId": workflow_id,
                        "workflowName": workflow_name,
                        "stepId": _pick(step, "stepId", "step_id", default=""),
                        "operationId": operation_id,
                        "sourceStepId": _pick(
                            dependency, "sourceStepId", "source_step_id", default=""
                        ),
                        "sourceJsonPath": _pick(
                            dependency, "sourceJsonPath", "source_json_path", default=""
                        ),
                        "targetStepId": _pick(
                            dependency, "targetStepId", "target_step_id", default=""
                        ),
                        "targetLocation": _pick(
                            dependency, "targetLocation", "target_location", default=""
                        ),
                        "variableName": _pick(
                            dependency, "variableName", "variable_name", default=""
                        ),
                        "confidence": _pick(dependency, "confidence", default=None),
                        "evidence": _pick(dependency, "evidence", default=""),
                    }
                )

    unpaged_actions = set(action_operations) - {
        action_id for actions in page_actions.values() for action_id in actions
    }
    ui_coverage_map = [
        {
            "pageUrl": page_url,
            "actionIds": sorted(action_ids),
            "actions": [
                {
                    "actionId": action_id,
                    "operationIds": sorted(action_operations.get(action_id, set())),
                }
                for action_id in sorted(action_ids)
            ],
        }
        for page_url, action_ids in sorted(page_actions.items())
    ]
    if unpaged_actions:
        ui_coverage_map.append(
            {
                "pageUrl": None,
                "actionIds": sorted(unpaged_actions),
                "actions": [
                    {
                        "actionId": action_id,
                        "operationIds": sorted(action_operations[action_id]),
                    }
                    for action_id in sorted(unpaged_actions)
                ],
            }
        )

    plan_assumptions = _unique_strings(_list(_pick(plan, "assumptions", default=[])))
    workflow_assumptions = _unique_strings(
        assumption
        for workflow in workflows
        for assumption in _list(_pick(workflow, "assumptions", default=[]))
    )
    plan_uncertainties = _unique_strings(_list(_pick(plan, "uncertainties", default=[])))
    workflow_uncertainties = _unique_strings(
        uncertainty
        for workflow in workflows
        for uncertainty in _list(_pick(workflow, "uncertainties", default=[]))
    )
    scenario_uncertainties = _unique_strings(
        _pick(scenario, "uncertainty", default=None)
        for _, scenario in scenarios
        if _pick(scenario, "uncertainty", default=None)
    )
    return {
        "schemaVersion": "1.0",
        "planId": _pick(plan, "planId", "plan_id", default="unknown"),
        "sourceRecordingIds": [_pick(plan, "recordingId", "recording_id", default="unknown")],
        "uiCoverageMap": ui_coverage_map,
        "apiInventory": [
            {
                "operationId": operation_id,
                "method": _pick(operation, "method", default=""),
                "origin": _pick(operation, "origin", default="${WEBTEST_BASE_URL}"),
                "normalizedPath": _pick(operation, "normalizedPath", "normalized_path", default=""),
                "pathParameters": _pick(operation, "pathParameters", "path_parameters", default=[]),
                "observedStatuses": _pick(operation, "observedStatuses", "observed_statuses", default=[]),
            }
            for operation_id, operation in sorted(operations.items())
        ],
        "endpointExamples": endpoint_examples,
        "workflows": [
            {
                "workflowId": _pick(workflow, "workflowId", "workflow_id"),
                "name": _pick(workflow, "name", default=""),
                "stepCount": len(_list(_pick(workflow, "steps", default=[]))),
                "assumptions": _pick(workflow, "assumptions", default=[]),
                "uncertainties": _pick(workflow, "uncertainties", default=[]),
            }
            for workflow in workflows
        ],
        "testMatrix": [
            {
                "workflowId": _pick(workflow, "workflowId", "workflow_id"),
                "workflowName": _pick(workflow, "name", default=""),
                "scenarioId": _pick(scenario, "scenarioId", "scenario_id"),
                "name": _pick(scenario, "name", default=""),
                "kind": _pick(scenario, "kind", default=""),
                "enabled": _pick(scenario, "enabled", default=True),
                "stepIds": _pick(scenario, "stepIds", "step_ids", default=[]),
                "expectedStatuses": _pick(
                    scenario, "expectedStatuses", "expected_statuses", default=[]
                ),
                "groups": _pick(scenario, "groups", default=[]),
            }
            for workflow, scenario in scenarios
        ],
        "planAssumptions": plan_assumptions,
        "planUncertainties": plan_uncertainties,
        "assumptions": _unique_strings([*plan_assumptions, *workflow_assumptions]),
        "uncertainties": _unique_strings(
            [*plan_uncertainties, *workflow_uncertainties, *scenario_uncertainties]
        ),
        "unsupportedTraffic": _pick(plan, "unsupportedTraffic", "unsupported_traffic", default=[]),
        "dataDependencies": sorted(
            data_dependencies,
            key=lambda dependency: (
                str(dependency["workflowId"]),
                str(dependency["targetStepId"]),
                str(dependency["targetLocation"]),
                str(dependency["sourceStepId"]),
                str(dependency["variableName"]),
            ),
        ),
        "generatedFiles": files,
        "coverageLimitations": [
            "Only approved workflows and recorded REST/JSON evidence are generated.",
            "UI coverage maps only recorded page/action/operation correlations.",
            "Destructive scenarios are excluded from the default TestNG suite.",
        ],
    }


def _unique_strings(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value is not None and str(value).strip()})


def _env_example() -> str:
    return """# Copy to a shell-specific local file if desired; this project does not load .env automatically.
WEBTEST_BASE_URL=
WEBTEST_AUTHORIZED_ORIGINS=
WEBTEST_ENVIRONMENT=local

# Optional common authentication configuration: none, bearer, basic, api_key, cookie.
WEBTEST_AUTH_TYPE=
WEBTEST_BEARER_TOKEN_ENV=API_TOKEN
API_TOKEN=
TEST_USERNAME=
TEST_PASSWORD=
API_KEY=
TEST_COOKIE=

# Required only by the corresponding adapter.
WEBTEST_API_KEY_NAME=
WEBTEST_API_KEY_LOCATION=header
WEBTEST_COOKIE_NAME=

WEBTEST_POLL_TIMEOUT_SECONDS=10
WEBTEST_POLL_INTERVAL_MILLIS=200
ALLOW_DESTRUCTIVE_TESTS=false
"""


def _generated_readme(project_name: str) -> str:
    return f"""# {project_name}

Deterministically generated by WebTest Agent from a human-approved plan. This
project runs without an LLM connection. Review `generation-report.json` and
`src/test/resources/flows/approved-plan.json` before executing it.

## Safety boundary

- Set `WEBTEST_BASE_URL` at runtime; no target URL is compiled into the tests.
- Set `WEBTEST_AUTHORIZED_ORIGINS` to an explicit comma-separated origin list.
- Negative tests run only when `WEBTEST_ENVIRONMENT` explicitly names a
  non-production environment.
- The default `testng.xml` excludes `destructive`. To run one deliberately,
  also set `ALLOW_DESTRUCTIVE_TESTS=true` and select that group explicitly.
- Authentication values come only from environment variables or values
  extracted during the current scenario. Reports pass through `SecretRedactor`.

## Run

Requires JDK 21 and Maven 3.9+.

```bash
export WEBTEST_BASE_URL='https://authorized-non-production.example'
export WEBTEST_AUTHORIZED_ORIGINS='https://authorized-non-production.example'
export WEBTEST_ENVIRONMENT='staging'
# Export any TEST_USERNAME/TEST_PASSWORD/API_TOKEN values required by the plan.
mvn test
```

Reports:

- HTML diagnostics: `target/webtest-report/index.html`
- TestNG/Surefire XML: `target/surefire-reports/`

Useful group selections:

```bash
mvn test -Dgroups=smoke
mvn test -Dgroups=positive
mvn test -Dgroups=negative
mvn test -Dgroups=asynchronous
```

Surefire 3.6 runs TestNG through its unified JUnit Platform provider, so Maven
uses the POM group/include settings rather than `testng.xml`. The XML file is
retained for IDEs and direct TestNG runners. To deliberately run the destructive
group, use both gates:

```bash
export ALLOW_DESTRUCTIVE_TESTS=true
mvn test -Dgroups=destructive -Dwebtest.excludedGroups=none
```
"""


def _json_path_lookup(value: Any, path: str) -> tuple[bool, Any]:
    normalized = path.removeprefix("$.")
    if normalized in {"", "$"}:
        return True, value
    current = value
    for part in normalized.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _normalize_json_path(path: str) -> str:
    return path[2:] if path.startswith("$.") else path


def _class_name(name: str, stable_id: str) -> str:
    base = _java_identifier(name, pascal=True) or "Workflow"
    suffix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}Scenarios_{suffix}Test"


def _method_name(name: str, stable_id: str) -> str:
    base = _java_identifier(name, pascal=False) or "scenario"
    suffix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{suffix}"


def _java_identifier(value: str, *, pascal: bool) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not words:
        return ""
    if pascal:
        result = "".join(word[:1].upper() + word[1:] for word in words)
    else:
        result = words[0][:1].lower() + words[0][1:] + "".join(word[:1].upper() + word[1:] for word in words[1:])
    if result[0].isdigit():
        result = "scenario" + result
    if result in _JAVA_RESERVED:
        result += "Scenario"
    return result


def _java_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return '"' + escaped + '"'


def _java_doc(value: str) -> str:
    return value.replace("*/", "* /").replace("\n", " ").replace("\r", " ")


def _java_line_comment(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ")


def _indent(value: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in value.splitlines())


def _canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, separators=(",", ": "))


def _compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _pick(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for name in names:
        if name in mapping:
            return mapping[name]
    return default


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _workflow_sort_key(workflow: Mapping[str, Any]) -> tuple[str, str]:
    return (_string(_pick(workflow, "workflowId", "workflow_id")), _string(_pick(workflow, "name")))


def _scenario_sort_key(scenario: Mapping[str, Any]) -> tuple[str, str]:
    return (_string(_pick(scenario, "scenarioId", "scenario_id")), _string(_pick(scenario, "name")))


def _step_sort_key(step: Mapping[str, Any]) -> tuple[int, str]:
    order = _pick(step, "order", default=0)
    return (order if isinstance(order, int) else 0, _string(_pick(step, "stepId", "step_id")))
