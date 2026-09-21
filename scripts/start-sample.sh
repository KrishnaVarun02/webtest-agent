#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec python3 "${ROOT_DIR}/sample-app/app.py" \
  --host "${WEBTEST_SAMPLE_HOST:-127.0.0.1}" \
  --port "${WEBTEST_SAMPLE_PORT:-8765}"

