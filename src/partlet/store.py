"""Where published files go: a key/value interface over R2 or a local directory."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

# Read the umask once without leaving it changed; os.umask can only set it.
_UMASK = os.umask(0)
os.umask(_UMASK)
TMP_PREFIX = ".partlet-tmp-"


class Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def list_dirs(self, prefix: str) -> list[str]: ...


class LocalPathError(ValueError):
    """Keys cannot retain their identities on the output filesystem."""


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

    def validate_keys(self, keys: Iterable[str]) -> None:
        """Probe file and directory identities without uploading any content.

        The probe lives on the output filesystem: case sensitivity and Unicode
        normalization are filesystem properties, not portable string rules.
        Publishes into one local directory must be serialized, as for sweeping.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as probe:
            identities: dict[tuple[int, int], str] = {}
            for key in keys:
                parts = check_key(key).split("/")
                path = Path(probe)
                for i, part in enumerate(parts):
                    path /= part
                    logical = "/".join(parts[: i + 1])
                    try:
                        if i < len(parts) - 1:
                            path.mkdir(exist_ok=True)
                        else:
                            path.touch(exist_ok=True)
                        stat = path.stat()
                    except OSError as exc:
                        raise LocalPathError(
                            f"Store key {key!r} cannot be represented on the local "
                            "filesystem; rename the Git path before publishing"
                        ) from exc
                    identity = (stat.st_dev, stat.st_ino)
                    previous = identities.setdefault(identity, logical)
                    if previous != logical or path.is_dir() != (i < len(parts) - 1):
                        raise LocalPathError(
                            f"Store paths {previous!r} and {logical!r} alias on the "
                            "local filesystem; rename the Git paths before publishing"
                        )

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TMP_PREFIX)
        try:
            # mkstemp creates the file 0600; previews must be readable by any
            # static HTTP server, which may run as another user.
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o666 & ~_UMASK)
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        keys = (
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(TMP_PREFIX)
        )
        return sorted(k for k in keys if k.startswith(prefix))

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        base = self._path(prefix.rstrip("/"))
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())
