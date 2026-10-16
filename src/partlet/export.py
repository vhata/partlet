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
    dest = dest.resolve()
    if dest.exists():
        raise ExportError(f"export destination {dest} already exists")
    if git_out("rev-parse", "--is-shallow-repository", cwd=monorepo) == "true":
        raise ExportError(
            f"{monorepo} is a shallow clone; publishing needs full history "
            "(use fetch-depth: 0 in actions/checkout)"
        )
    _require_directory(monorepo, branch, project.path)

    dest.parent.mkdir(parents=True, exist_ok=True)
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
        cwd=dest.parent,
    )
    check_export_repo(dest, monorepo)
    args = ["--quiet", "--replace-refs", "delete-no-add"]
    for path in project.all_paths:
        args += ["--path", f"{path}/", "--path-rename", f"{path}/:"]
    if mailmap is not None:
        args += ["--mailmap", str(mailmap.resolve())]
    run_filter_repo(*args, cwd=dest)

    check_export_repo(dest, monorepo)  # filter-repo has run since the last check
    if branch != "main":
        git("branch", "-m", branch, "main", cwd=dest)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=dest)
    return git_out("rev-parse", "refs/heads/main", cwd=dest)


def _require_directory(monorepo: Path, branch: str, path: str) -> None:
    if not _branch_exists(monorepo, branch):
        raise ExportError(f"branch {branch!r} not found in {monorepo}")
    proc_type = _object_type(monorepo, f"{branch}:{path}")
    if proc_type is None:
        raise ExportError(
            f"{path!r} does not exist on {branch}. If the directory moved, set path "
            "to its new location and add the old one to previous_paths."
        )
    if proc_type != "tree":
        raise ExportError(f"{path!r} on {branch} is not a directory")


def _branch_exists(repo: Path, branch: str) -> bool:
    try:
        git(
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}^{{commit}}",
            cwd=repo,
        )
    except GitError:
        return False
    return True


def _object_type(repo: Path, rev: str) -> str | None:
    try:
        return git_out("cat-file", "-t", rev, cwd=repo)
    except GitError:
        return None


def check_export_repo(dest: Path, monorepo: Path) -> None:
    """Raise unless `dest` is a bare repository of its own, outside `monorepo`.

    Every mutating git command in this module runs with `dest` as its cwd, so
    this is checked before each one: if `dest` were not itself the repository
    git finds there (git climbs to the enclosing repository from a plain
    directory), filter-repo would rewrite and gc that repository instead.
    """
    dest = dest.resolve()
    try:
        bare = git_out("rev-parse", "--is-bare-repository", cwd=dest)
        git_dir = Path(git_out("rev-parse", "--absolute-git-dir", cwd=dest)).resolve()
        mono_git_dir = Path(
            git_out("rev-parse", "--absolute-git-dir", cwd=monorepo)
        ).resolve()
    except (GitError, OSError) as e:
        raise ExportError(f"cannot inspect export repository {dest}: {e}") from e
    if bare != "true":
        raise ExportError(f"export repository {dest} is not a bare repository")
    if git_dir != dest:
        raise ExportError(f"git at {dest} resolves to {git_dir}, not {dest}")
    if git_dir == mono_git_dir:
        raise ExportError(f"export repository {dest} is the monorepo's own git dir")
    if dest.is_relative_to(monorepo.resolve()):
        raise ExportError(f"export repository {dest} is inside the monorepo")
