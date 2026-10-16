"""Extract one project's history from the monorepo with git filter-repo."""

from __future__ import annotations

from pathlib import Path

from partlet.gitutil import GitError, git, git_out, run_filter_repo
from partlet.manifest import Project


class ExportError(Exception):
    """The project cannot be exported from the monorepo as configured."""


def export_project(
    monorepo: Path,
    branch: str,
    project: Project,
    dest: Path,
    mailmap: Path | None = None,
) -> str:
    """Create a bare repo at `dest` holding only `project`'s history; return its tip."""
    if git_out("rev-parse", "--is-shallow-repository", cwd=monorepo) == "true":
        raise ExportError(
            f"{monorepo} is a shallow clone; publishing needs full history "
            "(use fetch-depth: 0 in actions/checkout)"
        )
    _require_directory(monorepo, branch, project.path)

    git(
        "clone",
        "--quiet",
        "--bare",
        "--no-local",
        "--no-tags",
        "--single-branch",
        "--branch",
        branch,
        str(monorepo.resolve()),
        str(dest),
        cwd=monorepo,
    )
    args = ["--quiet", "--force", "--replace-refs", "delete-no-add"]
    for path in project.all_paths:
        args += ["--path", f"{path}/", "--path-rename", f"{path}/:"]
    if mailmap is not None:
        args += ["--mailmap", str(mailmap.resolve())]
    run_filter_repo(*args, cwd=dest)

    if branch != "main":
        git("branch", "-m", branch, "main", cwd=dest)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=dest)
    return git_out("rev-parse", "refs/heads/main", cwd=dest)


def _require_directory(monorepo: Path, branch: str, path: str) -> None:
    proc_type = _object_type(monorepo, f"{branch}:{path}")
    if proc_type is None:
        raise ExportError(
            f"{path!r} does not exist on {branch}. If the directory moved, set path "
            "to its new location and add the old one to previous_paths."
        )
    if proc_type != "tree":
        raise ExportError(f"{path!r} on {branch} is not a directory")


def _object_type(repo: Path, rev: str) -> str | None:
    try:
        return git_out("cat-file", "-t", rev, cwd=repo)
    except GitError:
        return None
