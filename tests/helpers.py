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
