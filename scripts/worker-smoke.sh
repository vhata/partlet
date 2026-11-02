#!/usr/bin/env bash
# Exercise the real publisher and Worker through isolated local Wrangler R2.
set -euo pipefail
cd "$(dirname "$0")/.."
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL
[ -x .venv/bin/python ] || { echo "worker-smoke: run scripts/setup.sh first" >&2; exit 1; }
[ -x worker/node_modules/.bin/wrangler ] || { echo "worker-smoke: run scripts/setup.sh first" >&2; exit 1; }
exec .venv/bin/python worker/tools/smoke.py "$@"
