#!/usr/bin/env bash
# Validate the deploy bundle without contacting or deploying to Cloudflare.
set -euo pipefail
cd "$(dirname "$0")/../worker"
export WRANGLER_SEND_METRICS=false CLOUDFLARE_CF_FETCH_ENABLED=false
unset CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID CLOUDFLARE_API_KEY CLOUDFLARE_EMAIL
unset CF_API_TOKEN CF_ACCOUNT_ID CF_API_KEY CF_EMAIL

[ -x node_modules/.bin/wrangler ] || { echo "worker-bundle: run bash scripts/setup.sh first" >&2; exit 1; }
node_modules/.bin/wrangler deploy --dry-run --outdir .wrangler/dry-run
