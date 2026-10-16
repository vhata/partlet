#!/usr/bin/env bash
# Check Python formatting with ruff; never rewrites.
# Fix with: .venv/bin/ruff format src tests
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/ruff format --check "$@" src tests
