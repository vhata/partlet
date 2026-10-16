#!/usr/bin/env bash
# Prepare this worktree: install the git hooks. Idempotent; run after
# cloning, creating a worktree, or changing hook configuration.
# Python and Worker dependencies are added here as those components land.
set -euo pipefail
cd "$(dirname "$0")/.."

# Hooks live in the tracked .githooks/ directory. core.hooksPath is shared
# by every worktree of this clone.
git config core.hooksPath .githooks

echo "setup: done. Run 'bash scripts/check.sh' to verify the baseline."
