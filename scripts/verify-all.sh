#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
SAMPLE_PORT="${WEBTEST_VERIFY_PORT:-18765}"
SAMPLE_PID=""

cleanup() {
  if [[ -n "${SAMPLE_PID}" ]]; then
    kill "${SAMPLE_PID}" 2>/dev/null || true
    wait "${SAMPLE_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing ${PYTHON_BIN}. Run the root README setup first." >&2
  exit 2
fi

if [[ -z "${JAVA_HOME:-}" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
  export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
fi

npm --prefix "${ROOT_DIR}/extension" run check
"${PYTHON_BIN}" -m pytest "${ROOT_DIR}/orchestrator/tests" -q
PYTHONPATH="${ROOT_DIR}/generator" python3 -m unittest discover -s "${ROOT_DIR}/generator/tests" -v
python3 -m unittest discover -s "${ROOT_DIR}/sample-app" -p 'test_app.py' -v

PYTHONPATH="${ROOT_DIR}/generator" python3 -m webtest_generator.cli generate \
  --plan "${ROOT_DIR}/generator/fixtures/approved-plan.json" \
  --output-root "${ROOT_DIR}/generated" \
  --project-name webtest-sample-tests
"${PYTHON_BIN}" "${ROOT_DIR}/scripts/demo-pipeline.py" \
  --project-name webtest-e2e \
  --approve-fixture

python3 "${ROOT_DIR}/sample-app/app.py" --host 127.0.0.1 --port "${SAMPLE_PORT}" &
SAMPLE_PID=$!
for _ in {1..50}; do
  if curl -fsS --connect-timeout 1 --max-time 1 \
    "http://127.0.0.1:${SAMPLE_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
curl -fsS --connect-timeout 1 --max-time 2 "http://127.0.0.1:${SAMPLE_PORT}/health" >/dev/null

export WEBTEST_BASE_URL="http://127.0.0.1:${SAMPLE_PORT}"
export WEBTEST_AUTHORIZED_ORIGINS="http://127.0.0.1:${SAMPLE_PORT}"
export WEBTEST_ENVIRONMENT="local"
export TEST_USERNAME="sample_user"
export TEST_PASSWORD="sample_password"
mvn -B -ntp -f "${ROOT_DIR}/generated/webtest-sample-tests/pom.xml" test
curl -fsS -X POST -H 'Content-Type: application/json' -H 'X-Test-Environment: true' \
  --data '{}' "http://127.0.0.1:${SAMPLE_PORT}/api/test/reset" >/dev/null
mvn -B -ntp -f "${ROOT_DIR}/generated/webtest-e2e/pom.xml" test

echo "All WebTest Agent checks passed."
echo "Generator-fixture report: ${ROOT_DIR}/generated/webtest-sample-tests/target/webtest-report/index.html"
echo "Linked recording-to-plan report: ${ROOT_DIR}/generated/webtest-e2e/target/webtest-report/index.html"
