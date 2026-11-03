#!/usr/bin/env bash
# Full synthetic publisher CLI -> simulated S3 -> local R2 -> public Worker.
# Requires this worktree's Python tools and pinned Worker npm dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
for var in $(git rev-parse --local-env-vars); do unset "$var"; done
command -v node >/dev/null || { echo "e2e: Node is required" >&2; exit 1; }
[ -x worker/node_modules/.bin/wrangler ] || { echo "e2e: run bash scripts/setup.sh first" >&2; exit 1; }
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
bash scripts/test.sh -o addopts= -m e2e tests/e2e "$@"
