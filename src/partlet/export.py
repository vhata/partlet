"""Extract one project's history from the monorepo with git filter-repo."""

from __future__ import annotations

import os
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
    """Create a bare repo at `dest` holding only `project`'s history; return its tip.

    `dest` must not exist, and must lie outside the monorepo: the export always
    creates its own repository. A caller that exports the same project twice
    needs a fresh `dest` each time.
    """
    dest = dest.resolve()
    if dest.exists():
        raise ExportError(f"export destination {dest} already exists")
    _require_outside(dest, _monorepo_roots(monorepo)[1])
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
        "--origin",
        "origin",  # filter-repo's fresh-clone check wants exactly this remote
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


def _git_path(*args: str, cwd: Path) -> Path:
    path = Path(git_out("rev-parse", "--path-format=absolute", *args, cwd=cwd))
    return path if path.is_absolute() else cwd / path


def _same(a: Path, b: Path) -> bool:
    """Whether two paths name the same file, whatever their spelling or case."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _within(path: Path, root: Path) -> bool:
    """Whether `path` is `root` or lies below it, for as much of `path` as exists."""
    return any(_same(p, root) for p in (path, *path.parents))


def _monorepo_roots(monorepo: Path) -> tuple[list[Path], list[Path]]:
    """Return (git dirs, every root the export must stay out of) for `monorepo`.

    The git dirs are the monorepo's own and its common dir (they differ for a
    linked worktree). The roots add the work tree's top level, if it has one.
    """
    try:
        git_dirs = [
            _git_path("--absolute-git-dir", cwd=monorepo),
            _git_path("--git-common-dir", cwd=monorepo),
        ]
        roots = list(git_dirs)
        if git_out("rev-parse", "--is-inside-work-tree", cwd=monorepo) == "true":
            roots.append(_git_path("--show-toplevel", cwd=monorepo))
    except (GitError, OSError) as e:
        raise ExportError(f"cannot inspect monorepo {monorepo}: {e}") from e
    return git_dirs, roots


def _require_outside(dest: Path, roots: list[Path]) -> None:
    for root in roots:
        if _within(dest, root):
            raise ExportError(f"export repository {dest} is inside the monorepo {root}")


def check_export_repo(dest: Path, monorepo: Path) -> None:
    """Raise unless `dest` is a bare repository of its own, outside `monorepo`.

    Every mutating git command in this module runs with `dest` as its cwd, so
    this is checked before each one: if `dest` were not itself the repository
    git finds there (git climbs to an enclosing repository from a plain
    directory, and a `commondir` file or a linked worktree can point it at
    another one), filter-repo would rewrite and gc that repository instead.
    """
    dest = dest.resolve()
    git_dirs, roots = _monorepo_roots(monorepo)
    try:
        bare = git_out("rev-parse", "--is-bare-repository", cwd=dest)
        git_dir = _git_path("--absolute-git-dir", cwd=dest)
        common_dir = _git_path("--git-common-dir", cwd=dest)
    except (GitError, OSError) as e:
        raise ExportError(f"cannot inspect export repository {dest}: {e}") from e
    if bare != "true":
        raise ExportError(f"export repository {dest} is not a bare repository")
    if not _same(git_dir, dest):
        raise ExportError(f"git at {dest} resolves to {git_dir}, not {dest}")
    if not _same(common_dir, dest):
        raise ExportError(f"git at {dest} has common dir {common_dir}, not {dest}")
    if any(_same(d, m) for d in (git_dir, common_dir) for m in git_dirs):
        raise ExportError(f"export repository {dest} is the monorepo's own repository")
    _require_outside(dest, roots)
