"""Thin wrappers around the git command line."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run(
        cmd, check=False, cwd=cwd, input=input, env=full_env, capture_output=True
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"{' '.join(cmd[:3])}... failed ({proc.returncode}): {stderr}")
    return proc
