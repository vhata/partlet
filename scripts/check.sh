#!/usr/bin/env bash
# Local entry point: run the mechanical gates in order, cheapest first, and
# stop at the first failure, naming the gate. Hooks and CI call the same
# per-gate scripts. Gate scripts run with no arguments, forward any they are
# given to their tool, and must be executable (chmod +x scripts/*.sh).
# With --push, run only formatting, lint and type checks. The default full
# suite remains the gate before presenting changes and in required CI.
# See docs/QUALITY.md.
# This script runs the project's gates; hooks and docket/scripts/ci.sh run
# the vendored validators.
set -euo pipefail
cd "$(dirname "$0")/.."

# Gates are added to this list as the code they check lands.
gates=(fmt-check lint worker-lint worker-typecheck)
if [ "$#" -eq 0 ]; then
  gates+=(test worker-test worker-bundle worker-smoke)
elif [ "$#" -ne 1 ] || [ "$1" != "--push" ]; then
  echo "usage: bash scripts/check.sh [--push]" >&2
  exit 2
fi

for gate in "${gates[@]}"; do
  [ -x "scripts/$gate.sh" ] || { echo "check: scripts/$gate.sh missing or not executable" >&2; exit 1; }
  echo "==> $gate"
  if ! "scripts/$gate.sh"; then
    echo "check: gate '$gate' failed (scripts/$gate.sh)" >&2
    exit 1
  fi
done
echo "check: all selected gates passed"
