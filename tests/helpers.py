"""Helpers for building throwaway git repositories and serving directories."""

from __future__ import annotations

import functools
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from partlet.gitutil import git, git_out

EPOCH = 1767225600  # 2026-01-01T00:00:00Z


class Repo:
    """A non-bare repository with deterministic commit timestamps."""

    def __init__(self, path: Path, branch: str = "main"):
        self.path = path
        self._tick = 0
        path.mkdir(parents=True)
        git("init", "-q", "-b", branch, cwd=path)
        git("config", "user.name", "Test Author", cwd=path)
        git("config", "user.email", "author@example.com", cwd=path)
        git("config", "commit.gpgsign", "false", cwd=path)

    def write(self, rel: str, content: str | bytes) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        target.write_bytes(content)

    def symlink(self, rel: str, target: str) -> None:
        link = self.path / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

    def mv(self, src: str, dst: str) -> None:
        (self.path / dst).parent.mkdir(parents=True, exist_ok=True)
        git("mv", src, dst, cwd=self.path)

    def rm(self, rel: str) -> None:
        git("rm", "-r", "-q", rel, cwd=self.path)

    def commit(self, message: str) -> str:
        self._tick += 1
        date = f"{EPOCH + self._tick * 60} +0000"
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        git("add", "-A", cwd=self.path)
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.path, env=env)
        return git_out("rev-parse", "HEAD", cwd=self.path)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@contextmanager
def serve_directory(root: Path) -> Iterator[str]:
    """Serve `root` over plain HTTP on a free port; yields the base URL."""
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def repo_state_paths(
    git_dir: Path, common_dir: Path, gitconfig: Path | None
) -> dict[str, Path]:
    """The files whose contents `snapshot_repo_state` captures, by key.

    Reads files only; it never runs git. The branch ref is included only when
    HEAD names a branch (`ref: refs/heads/x`) and is keyed by its ref name.
    """
    paths = {
        "config": common_dir / "config",
        "config.worktree": git_dir / "config.worktree",
        "HEAD": git_dir / "HEAD",
    }
    try:
        head = (git_dir / "HEAD").read_text("utf-8", "replace").strip()
    except OSError:
        head = ""
    if head.startswith("ref:"):
        ref = head[len("ref:") :].strip()
        paths[ref] = common_dir / ref
    if gitconfig is not None:
        paths["gitconfig"] = gitconfig
    return paths


def snapshot_repo_state(
    git_dir: Path, common_dir: Path, gitconfig: Path | None
) -> dict[str, bytes | None]:
    """Raw bytes (None if missing) of the files a runaway test could rewrite."""
    state: dict[str, bytes | None] = {}
    for key, path in repo_state_paths(git_dir, common_dir, gitconfig).items():
        try:
            state[key] = path.read_bytes()
        except OSError:
            state[key] = None
    return state


def diff_repo_state(
    before: dict[str, bytes | None], after: dict[str, bytes | None]
) -> list[str]:
    """Keys whose captured bytes differ between two snapshots."""
    keys = before.keys() | after.keys()
    return sorted(k for k in keys if before.get(k) != after.get(k))
