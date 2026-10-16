#!/usr/bin/env bash
# Lint the project's own shell scripts with shellcheck. docket/ is vendored
# and checked upstream, so it is not linted here.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v shellcheck >/dev/null || { echo "lint: shellcheck not installed" >&2; exit 1; }

shopt -s nullglob
files=(scripts/*.sh .githooks/*)
[ "${#files[@]}" -gt 0 ] || { echo "lint: no shell scripts found" >&2; exit 1; }
shellcheck "$@" "${files[@]}"
echo "lint: ${#files[@]} shell scripts clean"
