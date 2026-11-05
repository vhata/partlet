#!/usr/bin/env bash
# Install the user-facing CLI and pinned tools, without development hooks.
set -euo pipefail

worker=1
if [ "$#" -eq 1 ] && [ "$1" = "--publisher-only" ]; then
  worker=0
elif [ "$#" -ne 0 ]; then
  echo "usage: bash scripts/install.sh [--publisher-only]" >&2
  exit 2
fi

command -v uv >/dev/null || { echo "install: uv is required (https://docs.astral.sh/uv/getting-started/installation/)" >&2; exit 1; }
partlet_source="$(cd "$(dirname "$0")/.." && pwd)"
echo "install: installing Partlet and Python dependencies with uv"
uv tool install --no-config --python 3.12 --reinstall "$partlet_source"
partlet_bin="$(uv tool dir --no-config --bin)/partlet"
if [ "$worker" -eq 1 ]; then
  "$partlet_bin" setup --worker
else
  "$partlet_bin" setup
fi
echo "install: done; run 'partlet --help' (use 'uv tool update-shell' if it is not on PATH)"
