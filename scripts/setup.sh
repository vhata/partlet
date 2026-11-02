#!/usr/bin/env bash
# Prepare this worktree: create its .venv, install the package with its dev
# dependencies, and install the git hooks. Idempotent; run after cloning,
# creating a worktree, or changing dependencies or hook configuration.
set -euo pipefail
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
cd "$(dirname "$0")/.."

# Python: a virtualenv per worktree with the package installed editable.
# uv finds or downloads a Python 3.12 interpreter.
command -v uv >/dev/null || { echo "setup: uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
[ -d .venv ] || uv venv --quiet --python 3.12 .venv
uv pip install --quiet --python .venv/bin/python -e '.[dev]'

# npm older than 11.19 silently ignores the dependency install allowlist.
command -v node >/dev/null || { echo "setup: Node is required; see worker/.node-version" >&2; exit 1; }
command -v npm >/dev/null || { echo "setup: npm >=11.19 is required" >&2; exit 1; }
node_pin="$(cat worker/.node-version)"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$node_major" != "${node_pin%%.*}" ]; then
  echo "setup: warning: Node $node_pin is pinned; using $(node --version)" >&2
fi
npm_version="$(npm --version)"
npm_major="${npm_version%%.*}"
npm_rest="${npm_version#*.}"
npm_minor="${npm_rest%%.*}"
if [ "$npm_major" -lt 11 ] || { [ "$npm_major" -eq 11 ] && [ "$npm_minor" -lt 19 ]; }; then
  echo "setup: npm >=11.19 is required to enforce allowScripts" >&2
  exit 1
fi
npm ci --prefix worker --no-audit --no-fund

# Hooks live in the tracked .githooks/ directory. core.hooksPath is shared
# by every worktree of this clone.
git config core.hooksPath .githooks

echo "setup: done. Run 'bash scripts/check.sh' to verify the baseline."
