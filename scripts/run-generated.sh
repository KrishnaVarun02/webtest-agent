#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="${1:-${ROOT_DIR}/generated/webtest-sample-tests}"

if [[ ! -f "${PROJECT_DIR}/pom.xml" ]]; then
  echo "Generated project not found: ${PROJECT_DIR}" >&2
  exit 2
fi

if [[ -z "${JAVA_HOME:-}" ]] && [[ "$(uname -s)" == "Darwin" ]]; then
  export JAVA_HOME="$(/usr/libexec/java_home -v 21)"
fi

: "${WEBTEST_BASE_URL:=http://127.0.0.1:8765}"
: "${WEBTEST_AUTHORIZED_ORIGINS:=http://127.0.0.1:8765}"
: "${TEST_USERNAME:=sample_user}"
: "${TEST_PASSWORD:=sample_password}"
: "${WEBTEST_ENVIRONMENT:=local}"
export WEBTEST_BASE_URL WEBTEST_AUTHORIZED_ORIGINS TEST_USERNAME TEST_PASSWORD WEBTEST_ENVIRONMENT

exec mvn -f "${PROJECT_DIR}/pom.xml" test
