#!/usr/bin/env bash
# Called from the action checkout; never discover source-repository config.
set -euo pipefail
cd "$(dirname "$0")/.."
for variable in ${!UV_@} ${!PIP_@} ${!PYTHON@}; do
  unset "$variable"
done
venv=$(mktemp -d "$RUNNER_TEMP/partlet-venv.XXXXXXXX")
uv --no-config --no-cache venv --quiet --python 3.12 "$venv"
uv --no-config --no-cache pip install --quiet --python "$venv/bin/python" \
  --require-hashes --no-build --index-url https://pypi.org/simple \
  -r action/requirements.txt
bash scripts/install-gitleaks.sh "$venv/bin"
echo "python=$venv/bin/python" >> "$GITHUB_OUTPUT"
