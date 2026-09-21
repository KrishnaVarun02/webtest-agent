# End-to-end demonstration

These commands exercise the checked-in sanitized recording through the real
normalizer, LangGraph planning graph, SQLite review state, explicit approval
gate, deterministic Java generator, sample application, Maven/TestNG suite,
and Extent HTML report. No LLM or API key is used.

Run all commands from `webtest-agent/` after completing the root README setup.

## 1. Start the local services

Terminal A:

```bash
./scripts/start-sample.sh
```

Terminal B:

```bash
./scripts/start-orchestrator.sh
```

Terminal C:

```bash
curl --fail --silent --show-error http://127.0.0.1:8765/health
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

The sample UI is at <http://127.0.0.1:8765/> and the human review screen is at
<http://127.0.0.1:8000/review>.

## 2. Produce an editable draft

```bash
./.venv/bin/python scripts/demo-pipeline.py --project-name webtest-e2e
```

The command prints the `planId` and writes
`generated/webtest-e2e-draft-plan.json`. Paste the ID into the review screen to
inspect or edit workflow names, expected statuses, assertions, scenario flags,
dependencies, assumptions, and supplied test-data references. After saving
edits, either approve in the UI or preserve and explicitly approve that exact
persisted revision with:

```bash
./.venv/bin/python scripts/demo-pipeline.py \
  --project-name webtest-e2e \
  --approve-plan-id PLAN_ID
```

This mode loads the existing SQLite plan and never recreates or discards its
edits. No code is generated without approval.

For the deterministic end-to-end fixture demonstration, the following command
applies the checked-in human-reviewed sample decisions to the immutable API
inventory, persists that edited revision, explicitly approves it, and generates
the project. The review adds only behavior evidenced by the recording: repeated
job-status polling and the final record read.

```bash
./.venv/bin/python scripts/demo-pipeline.py \
  --project-name webtest-e2e \
  --approve-fixture
```

The reviewed draft and exact approved plan are retained at
`generated/webtest-e2e-reviewed-plan.json` and
`generated/webtest-e2e-approved-plan.json`; the Maven project is at
`generated/webtest-e2e/`; and the generation report is written below
`orchestrator/reports/`.

## 3. Run the generated tests

On macOS, select Java 21 first:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
```

Then reset the sample state and run the suite:

```bash
curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' -H 'X-Test-Environment: true' \
  --data '{}' http://127.0.0.1:8765/api/test/reset
./scripts/run-generated.sh generated/webtest-e2e
```

The default suite exercises login/token setup, create/read/update with ID
extraction and reuse, one-field validation failure, unauthorized access,
bounded asynchronous polling, and final-state verification. Destructive tests
are excluded. Reports are:

- `generated/webtest-e2e/target/webtest-report/index.html`
- `generated/webtest-e2e/target/surefire-reports/`

## 4. Deliberately fail one assertion

This creates a separate plan/project so it cannot corrupt the passing demo:

```bash
./.venv/bin/python scripts/make-broken-plan.py
PYTHONPATH=generator python3 -m webtest_generator.cli generate \
  --plan generated/broken-approved-plan.json \
  --output-root generated \
  --project-name webtest-broken-assertion
curl --fail --silent --show-error \
  -X POST -H 'Content-Type: application/json' -H 'X-Test-Environment: true' \
  --data '{}' http://127.0.0.1:8765/api/test/reset
./scripts/run-generated.sh generated/webtest-broken-assertion
```

The final command is expected to exit nonzero. Its sanitized report remains at
`generated/webtest-broken-assertion/target/webtest-report/index.html` and shows
the scenario/step, sanitized exchange, expected and actual value, elapsed time,
failure reason, and stack trace.

## 5. One-command verification

With the Python, Node, Java, and Maven prerequisites installed:

```bash
./scripts/verify-all.sh
```

This rebuilds the extension, runs all TypeScript/Python tests, regenerates both
the canonical generator fixture and the linked recording-to-reviewed-plan
project, starts an isolated sample server, and runs both passing Maven suites.
