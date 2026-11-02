"""Check the external tools whose versions published output depends on."""

from __future__ import annotations

import importlib.metadata
import re
from dataclasses import dataclass
from pathlib import Path

from partlet import __version__
from partlet.gitutil import GitError, git_out
from partlet.scan import GITLEAKS_VERSION, ScanError, check_gitleaks

# Export commit hashes depend on filter-repo's behaviour (docs/DECISIONS.md),
# so publishing refuses any other release. Must match pyproject.toml.
FILTER_REPO_VERSION = "2.47.0"
# rev-parse --path-format and first-parent merge diffs need git 2.31.
MIN_GIT = (2, 31)


class ToolError(Exception):
    """A required tool is missing or is not the pinned version."""


@dataclass(frozen=True)
class Tools:
    versions: dict[str, str]
    gitleaks: str | None  # path of the checked gitleaks binary


def check_tools(*, gitleaks: bool) -> Tools:
    try:
        filter_repo = importlib.metadata.version("git-filter-repo")
    except importlib.metadata.PackageNotFoundError as e:
        raise ToolError("git-filter-repo is not installed") from e
    if filter_repo != FILTER_REPO_VERSION:
        raise ToolError(
            f"git-filter-repo {filter_repo} is installed; publishing needs exactly "
            f"{FILTER_REPO_VERSION}, because export commit hashes depend on it"
        )
    try:
        git_version = git_out("--version", cwd=Path.cwd()).removeprefix("git version ")
    except (GitError, OSError) as e:
        raise ToolError(f"cannot run git: {e}") from e
    found = re.match(r"(\d+)\.(\d+)", git_version)
    if found is None or tuple(map(int, found.groups())) < MIN_GIT:
        raise ToolError(
            f"git {git_version} is too old; partlet needs git 2.31 or newer"
        )
    versions = {
        "partlet": __version__,
        "git": git_version,
        "git-filter-repo": filter_repo,
    }
    binary = None
    if gitleaks:
        try:
            binary = check_gitleaks()
        except ScanError as e:
            raise ToolError(str(e)) from e
        versions["gitleaks"] = GITLEAKS_VERSION
    return Tools(versions, binary)
