#!/usr/bin/env bash
# Run the Python test suite. pytest exits 5 when it collects no tests,
# so an empty suite fails this gate.
set -euo pipefail
cd "$(dirname "$0")/.."

# Git hooks export GIT_DIR and friends; drop them so the tests cannot act on the enclosing repository.
for var in $(git rev-parse --local-env-vars); do unset "$var"; done

.venv/bin/pytest -q "$@"
