# Architecture

WebTest Agent is a local monorepo with a deliberately small deployment shape.

```text
Authorized Chrome tab
  |  UI actions + XHR/fetch (sanitized in browser)
  v
MV3 DevTools extension
  |  versioned recording JSON
  v
FastAPI + LangGraph orchestrator ---- SQLite checkpoints / review state
  |  normalized operations -> workflows -> editable scenarios
  |  human approval gate
  v
Deterministic Python generator
  |  approved plan
  v
Java 21 / TestNG / Rest Assured project
  |  requests only to an explicitly allowed non-production origin
  v
Sample app or authorized target ---- sanitized HTML execution report
```

## Components

- `extension/` captures one inspected Chrome tab, records safe UI action
  metadata, supports bounded exploration, filters noise, and exports sanitized
  versioned JSON or HAR-compatible JSON.
- `orchestrator/` validates recordings, normalizes and deduplicates endpoints,
  plans flows/scenarios through typed LangGraph state, persists resumable runs,
  serves the review interface, and gates generation on approval.
- `generator/` contains deterministic Java templates and a CLI/import API.
- `sample-app/` is a dependency-free local REST/JSON site with auth, CRUD,
  validation, authorization failure, and an asynchronous status flow.
- `generated/` holds generated Maven projects and their reports.
- `scripts/` contains repeatable validation and demonstration commands.

## Data flow and approval boundary

The extension correlates each request with the most recent action. The
normalizer removes unsupported/noise traffic, redacts again, parameterizes
dynamic path segments, and preserves distinct useful examples. Planning marks
inferences and uncertainty; it does not invent business rules. The review API
allows names, expected statuses, assertions, enabled flags, and supplied test
data to be edited. Generation rejects plans without explicit approval.

## Persistence

SQLite holds sanitized recordings, plans, approvals, and graph checkpoints.
Recording, plan, and report payloads carry explicit schema versions. No Redis,
vector database, cloud service, or background infrastructure is required.

## Extension points

Normalizer, model-provider, action-policy, generator-backend, auth-provider,
and report-event interfaces isolate future GraphQL, Playwright, Firefox, and
additional output-language support. Those features are not implemented in v1.

