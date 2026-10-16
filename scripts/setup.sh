#!/usr/bin/env bash
# Prepare this worktree: install the git hooks. Idempotent; run after
# cloning, creating a worktree, or changing hook configuration.
# Worker dependencies are added here when the Worker lands.
set -euo pipefail
cd "$(dirname "$0")/.."

# Python: a virtualenv per worktree with the package installed editable.
# uv finds or downloads a Python 3.12 interpreter.
command -v uv >/dev/null || { echo "setup: uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
[ -d .venv ] || uv venv --quiet --python 3.12 .venv
uv pip install --quiet --python .venv/bin/python -e '.[dev]'

# Hooks live in the tracked .githooks/ directory. core.hooksPath is shared
# by every worktree of this clone.
git config core.hooksPath .githooks

echo "setup: done. Run 'bash scripts/check.sh' to verify the baseline."
