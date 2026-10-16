"""Where published files go: a key/value interface over R2 or a local directory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def list_dirs(self, prefix: str) -> list[str]: ...


def check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid store key {key!r}")
    return key


class LocalStore:
    """Stores each key as a file under `root`. Used for previews and tests."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*check_key(key).split("/"))

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        keys = (
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(".tmp-")
        )
        return sorted(k for k in keys if k.startswith(prefix))

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        base = self._path(prefix.rstrip("/"))
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())
