"""Downloadable archives of an export tip."""

from __future__ import annotations

from pathlib import Path

from partlet.gitutil import git

ARCHIVE_FORMATS = ("tar.gz", "zip")


def make_archives(repo: Path, name: str, tip: str) -> dict[str, bytes]:
    return {
        fmt: git(
            "archive", f"--format={fmt}", f"--prefix={name}/", tip, cwd=repo
        ).stdout
        for fmt in ARCHIVE_FORMATS
    }
