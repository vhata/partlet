#!/usr/bin/env bash
# Typecheck the Worker and its tests. First confirm that the generated
# worker-configuration.d.ts still matches wrangler.toml and the Worker's
# exports; regenerate it with: (cd worker && npm run types)
set -euo pipefail
cd "$(dirname "$0")/../worker"
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL
unset CF_API_TOKEN CF_ACCOUNT_ID CF_API_KEY CF_EMAIL

[ -x node_modules/.bin/tsc ] || { echo "worker-typecheck: run bash scripts/setup.sh first" >&2; exit 1; }
node_modules/.bin/wrangler types --strict-vars=false --check
node_modules/.bin/tsc -p tsconfig.json
node_modules/.bin/tsc -p test/tsconfig.json
echo "worker-typecheck: clean"
