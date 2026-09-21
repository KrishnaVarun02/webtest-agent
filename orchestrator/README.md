# WebTest Agent orchestrator

This package is the local, privacy-first planning service for WebTest Agent. It
validates and sanitizes browser recordings, normalizes and deduplicates API
operations, builds editable workflow/scenario plans, waits for explicit human
approval, invokes the deterministic Java generator, validates the generated
project, and produces sanitized generation reports.

It works without an LLM. Set `WEBTEST_LLM_PROVIDER=openai`, `OPENAI_API_KEY`,
and optionally `OPENAI_MODEL` to enable the provider adapter. Recordings are
sanitized before persistence or model calls; API keys are never stored.

```bash
cd webtest-agent/orchestrator
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test,llm]'
uvicorn webtest_agent_orchestrator.api:app --reload --port 8000
pytest
```

Open <http://127.0.0.1:8000/review> for the minimal review UI. Runtime data is
written below `data/` and reports below `reports/` unless overridden with
`WEBTEST_DB_PATH`, `WEBTEST_REPORT_ROOT`, or `WEBTEST_GENERATED_ROOT`.

The public API is documented at <http://127.0.0.1:8000/docs>. The extension
compatibility routes are `POST /api/v1/explore/next`, `POST /api/v1/review`,
and `POST /api/v1/generate`.
