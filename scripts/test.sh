#!/usr/bin/env bash
# Run the Python suite. Require at least one executed case, preserving
# pytest's failure codes and collection-only behavior.
set -euo pipefail
cd "$(dirname "$0")/.."

# Git hooks export GIT_DIR and friends; drop them so the tests cannot act on the enclosing repository.
for var in $(git rev-parse --local-env-vars); do unset "$var"; done

.venv/bin/python tests/pytest_gate.py -q "$@"
