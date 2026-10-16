#!/usr/bin/env bash
# Run the Python test suite. pytest exits 5 when it collects no tests,
# so an empty suite fails this gate.
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/pytest -q "$@"
