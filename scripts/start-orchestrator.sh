#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Run the root README setup commands first." >&2
  exit 2
fi

export WEBTEST_DB_PATH="${WEBTEST_DB_PATH:-${ROOT_DIR}/orchestrator/data/webtest-agent.db}"
export WEBTEST_GENERATED_ROOT="${WEBTEST_GENERATED_ROOT:-${ROOT_DIR}/generated}"
export WEBTEST_GENERATOR_ROOT="${WEBTEST_GENERATOR_ROOT:-${ROOT_DIR}/generator}"
export WEBTEST_REPORT_ROOT="${WEBTEST_REPORT_ROOT:-${ROOT_DIR}/orchestrator/reports}"

exec "${PYTHON_BIN}" -m uvicorn webtest_agent_orchestrator.main:app \
  --app-dir "${ROOT_DIR}/orchestrator/src" \
  --host "${WEBTEST_ORCHESTRATOR_HOST:-127.0.0.1}" \
  --port "${WEBTEST_ORCHESTRATOR_PORT:-8000}"

