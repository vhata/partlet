"""Thin wrappers around the git command line."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Variables that point git at a particular repository, as listed by
# `git rev-parse --local-env-vars`. Git exports some of them to hooks, so a
# partlet run from a hook would otherwise act on the enclosing repository
# instead of the one named by cwd.
_LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


class GitError(Exception):
    """A git command failed."""


def git(
    *args: str,
    cwd: Path,
    input: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return _run(["git", *args], cwd=cwd, input=input, env=env)


def git_out(*args: str, cwd: Path, input: bytes | None = None) -> str:
    return git(*args, cwd=cwd, input=input).stdout.decode("utf-8").strip()


def run_filter_repo(*args: str, cwd: Path) -> None:
    """Run the git-filter-repo installed alongside this package."""
    _run([sys.executable, "-m", "git_filter_repo", *args], cwd=cwd)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    input: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    inherited = {k: v for k, v in os.environ.items() if k not in _LOCAL_ENV_VARS}
    full_env = {**inherited, **(env or {})}
    proc = subprocess.run(
        cmd, check=False, cwd=cwd, input=input, env=full_env, capture_output=True
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"{' '.join(cmd[:3])}... failed ({proc.returncode}): {stderr}")
    return proc
