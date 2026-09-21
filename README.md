# WebTest Agent

WebTest Agent is a local, authorization-first platform that records REST/JSON
traffic triggered by a Chrome UI, correlates it with safe UI actions, plans
evidence-based API workflows, requires human approval, and emits runnable Java
21/TestNG tests with sanitized diagnostics. The default path is fully offline;
neither planning nor generated test execution requires an LLM connection.

Use it only for websites you own or are explicitly authorized to test.

## Architecture

```text
Authorized Chrome tab
  -> MV3 DevTools capture + safe UI actions (sanitize in browser)
  -> FastAPI / Pydantic / LangGraph orchestrator
  -> SQLite draft, edit, approval, and resumable run state
  -> deterministic Python generator
  -> Java 21 / TestNG / Rest Assured / Awaitility Maven project
  -> authorized sample or non-production API
  -> sanitized generation + Extent execution reports
```

The monorepo is split into `extension/`, `orchestrator/`, `generator/`,
`sample-app/`, `generated/`, `docs/`, and `scripts/`. See
[`docs/architecture.md`](docs/architecture.md) for component boundaries.

## Supported scope

Version one supports Chrome, one inspected tab, DevTools-open capture,
same-origin manual or bounded AI exploration, XHR/fetch, REST, JSON and
form-urlencoded bodies, common auth patterns, sanitized JSON/HAR export,
human-reviewed plans, and Java/TestNG generation.

WebSockets, SSE, gRPC, protobuf, binary or encrypted request bodies, uploads,
multi-tab/mobile flows, CAPTCHA, payments, and arbitrary third-party sites are
record-only or unsupported for semantic automation. GraphQL, Playwright UI
generation, Firefox, and other output languages are explicit future extension
points, not partial v1 features.

## Prerequisites

- Chrome with permission to load an unpacked extension
- Node.js 22+ and npm
- Python 3.11+
- JDK 21 and Maven 3.9+
- `curl` for the copied demo commands

No OpenAI key is needed. Optional model-backed exploration uses the OpenAI
Responses provider only when `WEBTEST_LLM_PROVIDER=openai` and
`OPENAI_API_KEY` are set; sanitized structured input is sent with storage
disabled. Offline deterministic behavior remains the default.

## Setup

From this directory:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -e './orchestrator[test,llm]'
npm --prefix extension ci
npm --prefix extension run check
```

On macOS, select Java 21 for Maven:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 21)
java -version
mvn -version
```

## Start the sample application and orchestrator

Use separate terminals from this directory:

```bash
./scripts/start-sample.sh
```

```bash
./scripts/start-orchestrator.sh
```

Verify both:

```bash
curl --fail --silent --show-error http://127.0.0.1:8765/health
curl --fail --silent --show-error http://127.0.0.1:8000/health
```

Open <http://127.0.0.1:8765/> for the sample website and
<http://127.0.0.1:8000/review> for plan review. SQLite state is kept in
`orchestrator/data/`; generation reports are written to
`orchestrator/reports/`.

## Load the Chrome extension

1. Run `npm --prefix extension run build`.
2. Open `chrome://extensions`, enable **Developer mode**, and choose
   **Load unpacked**.
3. Select the absolute `webtest-agent/extension/dist` directory.
4. Open an authorized site, open DevTools, choose **WebTest Agent**, and reload
   the inspected page when prompted.

Chrome permissions are intentionally narrow in behavior: the DevTools network
API captures completed XHR/fetch metadata and available bodies; `tabs` reaches
only the inspected tab; `storage` retains sanitized settings/capture state;
and `<all_urls>` permits a generic tool to operate on a user-chosen site.
Runtime checks still require exact allowed origins and refuse unrelated hosts.
See [`extension/README.md`](extension/README.md) for the detailed rationale.

## Record, explore, review, and generate

In the DevTools panel:

1. Enter an exact origin such as `http://127.0.0.1:8765`, plus optional
   include/exclude patterns, then choose **Start**.
2. Use the site normally. Inspect the action-correlated API list and uncheck
   analytics, telemetry, static, advertising, tracking, or irrelevant calls.
3. Optionally choose **AI Explore**. The model receives only a compact
   accessibility snapshot and must return one schema-validated action. The
   browser enforces origin/action/time/retry limits and asks before likely
   server mutations. It never executes model-provided JavaScript.
4. Choose **Review**, edit the evidence-backed plan, supply only test-data
   references, and approve or reject workflows.
5. Choose **Generate** only after approval. Draft or edited-unapproved plans
   are rejected by the orchestrator.

Manual capture and generation work when AI exploration is disabled. JSON and
HAR exports are sanitized before they leave the extension.

## Exact fixture demo

The complete reproducible walkthrough is in [`docs/demo.md`](docs/demo.md).
The shortest passing path, after both local services are running, is:

```bash
./.venv/bin/python scripts/demo-pipeline.py \
  --project-name webtest-e2e \
  --approve-fixture
./scripts/run-generated.sh generated/webtest-e2e
```

The explicit `--approve-fixture` applies a checked-in, evidence-backed reviewed
sample revision before approval. Interactive use should inspect/edit the draft
at `/review` and then pass its ID with `--approve-plan-id`. Generated tests validate
`WEBTEST_BASE_URL` against `WEBTEST_AUTHORIZED_ORIGINS`; negative tests also
require a named non-production environment. Destructive tests are excluded by
default and additionally require `ALLOW_DESTRUCTIVE_TESTS=true`.

Reports:

- Generation: `orchestrator/reports/report-*.html`
- Passing fixture execution:
  `generated/webtest-e2e/target/webtest-report/index.html`
- Surefire/TestNG XML: `generated/webtest-e2e/target/surefire-reports/`
- Deliberate failure:
  `generated/webtest-broken-assertion/target/webtest-report/index.html`

## Build and test

Run every normal verification, including both the deterministic generator
fixture and the linked recording-to-reviewed-plan project against an isolated
sample server:

```bash
./scripts/verify-all.sh
```

Individual checks:

```bash
npm --prefix extension run check
./.venv/bin/python -m pytest orchestrator/tests -q
PYTHONPATH=generator python3 -m unittest discover -s generator/tests -v
python3 -m unittest discover -s sample-app -p 'test_app.py' -v
```

## Privacy and safety invariants

Passwords, authorization/cookie headers, API keys, access/refresh tokens,
credentials, session IDs, and secret-named query/body fields are removed
before storage, model calls, code generation, logs, and reports. Tests seed
marker secrets and scan browser recordings, SQLite rows, provider payloads,
generated files, and reports. Captured destructive requests are never replayed
automatically. Negative tests require an explicit non-production setting.

The supplied reference ZIP was inspected read-only as untrusted content and
was not executed or copied. It contained sensitive and generated artifacts;
only generic framework patterns are described in
[`docs/reference-patterns.md`](docs/reference-patterns.md).

## Troubleshooting

- **Panel missing:** rebuild, reload the unpacked extension, reopen DevTools,
  and reload the page.
- **Recording refuses to start:** configure an exact `scheme://host:port`
  allowed origin and reload after DevTools is open.
- **Orchestrator unreachable:** confirm `/health` on port 8000 and that no
  proxy rewrites loopback traffic.
- **Java release 21 not supported:** point `JAVA_HOME` to a JDK 21 installation
  and confirm `mvn -version` reports it.
- **Generated origin rejected:** make `WEBTEST_BASE_URL` exactly match one
  comma-separated entry in `WEBTEST_AUTHORIZED_ORIGINS`.
- **Negative test refused:** set `WEBTEST_ENVIRONMENT=local`, `test`,
  `development`, or another reviewed non-production name.
- **Expected SLF4J warning:** Rest Assured/TestNG dependencies may report that
  no optional logging provider is installed; execution/reporting is unaffected.

## Known limitations

The browser extension was built and fixture-tested here but not visually
driven through Chrome in this environment. Schema inference is evidence-based,
not a replacement for an OpenAPI contract. Cleanup is generated only when a
safe observed cleanup exists. Coverage describes recorded pages and traffic,
not the entire target. Model-assisted exploration quality depends on the
provided accessible names, but all safety enforcement remains deterministic.

Design and data-flow details are in `docs/recording-schema.md`,
`docs/langgraph-flow.md`, `docs/security.md`, and
`docs/generated-framework.md`.
