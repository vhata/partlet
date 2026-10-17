"""Read the files of an export tip."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import git

SIZE_CAP = 1024 * 1024
SYMLINK_MODE = b"120000"


@dataclass(frozen=True)
class FileEntry:
    path: str
    data: bytes
    is_symlink: bool = False

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)

    @property
    def parent(self) -> str:
        return posixpath.dirname(self.path)

    @property
    def size(self) -> int:
        return len(self.data)


def read_tree(repo: Path, tip: str) -> list[FileEntry]:
    listing = git("ls-tree", "-r", "-z", "--full-tree", tip, cwd=repo).stdout
    items: list[tuple[bytes, str, str]] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind != b"blob":
            continue  # submodules (gitlinks) have no content here
        items.append((mode, sha.decode(), raw_path.decode("utf-8", "replace")))
    if not items:
        return []

    batch = git(
        "cat-file",
        "--batch",
        cwd=repo,
        input="".join(f"{s}\n" for _, s, _ in items).encode(),
    ).stdout
    entries = []
    pos = 0
    for mode, _sha, path in items:
        newline = batch.index(b"\n", pos)
        size = int(batch[pos:newline].split()[2])
        start = newline + 1
        entries.append(
            FileEntry(path, batch[start : start + size], mode == SYMLINK_MODE)
        )
        pos = start + size + 1  # content is followed by a newline
    return sorted(entries, key=lambda e: e.path)


def is_binary(data: bytes) -> bool:
    if b"\0" in data[:8000]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def is_viewable(entry: FileEntry) -> bool:
    return not entry.is_symlink and entry.size <= SIZE_CAP and not is_binary(entry.data)
