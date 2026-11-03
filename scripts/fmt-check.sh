#!/usr/bin/env bash
# Check Python and Markdown formatting; never rewrites.
# Fix with: .venv/bin/ruff format src tests action
#           bash scripts/fmt-markdown.sh
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/ruff format --check "$@" src tests action
bash scripts/fmt-markdown.sh --check
