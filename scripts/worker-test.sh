#!/usr/bin/env bash
# Run the Worker tests on the Workers runtime (vitest with
# @cloudflare/vitest-plugin). vitest exits 1 when it finds no test files,
# so an empty suite fails this gate.
set -euo pipefail
cd "$(dirname "$0")/../worker"
export WRANGLER_SEND_METRICS=false
# The tests use local, simulated bindings only; make sure no Cloudflare
# credentials are visible to them.
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL

[ -x node_modules/.bin/vitest ] || { echo "worker-test: run bash scripts/setup.sh first" >&2; exit 1; }
node_modules/.bin/vitest run "$@"
