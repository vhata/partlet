#!/usr/bin/env bash
# Typecheck the Worker and its tests. First confirm that the generated
# worker-configuration.d.ts still matches wrangler.toml and the Worker's
# exports; regenerate it with: (cd worker && npm run types)
set -euo pipefail
cd "$(dirname "$0")/../worker"
export WRANGLER_SEND_METRICS=false

[ -x node_modules/.bin/tsc ] || { echo "worker-typecheck: run bash scripts/setup.sh first" >&2; exit 1; }
node_modules/.bin/wrangler types --strict-vars=false --check
node_modules/.bin/tsc -p tsconfig.json
node_modules/.bin/tsc -p test/tsconfig.json
echo "worker-typecheck: clean"
