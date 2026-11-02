#!/usr/bin/env bash
# Lint and format-check the Worker with Biome; never rewrites.
# Fix with: (cd worker && node_modules/.bin/biome check --write .)
set -euo pipefail
cd "$(dirname "$0")/../worker"

[ -x node_modules/.bin/biome ] || { echo "worker-lint: run bash scripts/setup.sh first" >&2; exit 1; }
node_modules/.bin/biome check --error-on-warnings "$@" .
../.venv/bin/ruff format --check tools
../.venv/bin/ruff check tools
