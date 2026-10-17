"""Load and validate partlet.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")

SITE_KEYS = {"source", "branch", "base_url", "mailmap"}
PROJECT_KEYS = {"path", "previous_paths", "description", "approved", "allow_rewrite_of"}


class ManifestError(Exception):
    """partlet.toml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class Site:
    source: str
    branch: str
    base_url: str
    mailmap: str | None = None


@dataclass(frozen=True)
class Project:
    name: str
    path: str
    previous_paths: tuple[str, ...] = ()
    description: str = ""
    approved: str | None = None
    allow_rewrite_of: str | None = None

    @property
    def all_paths(self) -> tuple[str, ...]:
        return (self.path, *self.previous_paths)


@dataclass(frozen=True)
class Manifest:
    site: Site
    projects: dict[str, Project]


def load_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"cannot read {path}: {e}") from e
    return parse_manifest(text)


def parse_manifest(text: str) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"invalid TOML: {e}") from e
    site = _parse_site(data.get("site"))
    raw_projects = data.get("projects", {})
    if not isinstance(raw_projects, dict):
        raise ManifestError("[projects] must be a table")
    projects = {name: _parse_project(name, body) for name, body in raw_projects.items()}
    return Manifest(site=site, projects=projects)


def normalize_path(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{where}: path must be a string")
    if "\\" in value:
        raise ManifestError(f"{where}: invalid path {value!r}")
    parts = PurePosixPath(value.strip("/")).parts
    if not parts or parts == (".",) or any(p in (".", "..") for p in parts):
        raise ManifestError(f"{where}: invalid path {value!r}")
    # PurePosixPath collapses "a/./b" to "a/b", so check the raw segments too.
    if any(seg in (".", "..") for seg in value.strip("/").split("/")):
        raise ManifestError(f"{where}: invalid path {value!r}")
    return "/".join(parts)


def _check_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _str(
    raw: dict[str, Any], key: str, where: str, default: str | None = None
) -> str | None:
    value = raw.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ManifestError(f"{where}.{key} must be a string")
    return value


def _sha(raw: dict[str, Any], key: str, where: str) -> str | None:
    value = _str(raw, key, where)
    if value is not None and not SHA_RE.fullmatch(value):
        raise ManifestError(f"{where}.{key} must be a full 40-character commit hash")
    return value


def _parse_site(raw: Any) -> Site:
    if not isinstance(raw, dict):
        raise ManifestError("missing [site] table")
    _check_keys(raw, SITE_KEYS, "site")
    source = _str(raw, "source", "site")
    if source is None or not NAME_RE.fullmatch(source):
        raise ManifestError(f"site.source must match {NAME_RE.pattern}")
    base_url = _str(raw, "base_url", "site")
    if not base_url:
        raise ManifestError("site.base_url is required")
    return Site(
        source=source,
        branch=_str(raw, "branch", "site", "main"),
        base_url=base_url.rstrip("/"),
        mailmap=_str(raw, "mailmap", "site"),
    )


def _parse_project(name: str, raw: Any) -> Project:
    where = f"projects.{name}"
    if not NAME_RE.fullmatch(name):
        raise ManifestError(f"project name {name!r} must match {NAME_RE.pattern}")
    if name.endswith(".git"):
        raise ManifestError(f"project name {name!r} must not end in .git")
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be a table")
    _check_keys(raw, PROJECT_KEYS, where)
    if "path" not in raw:
        raise ManifestError(f"{where}.path is required")
    path = normalize_path(raw["path"], f"{where}.path")
    previous_raw = raw.get("previous_paths", [])
    if not isinstance(previous_raw, list):
        raise ManifestError(f"{where}.previous_paths must be a list of strings")
    previous = tuple(normalize_path(p, f"{where}.previous_paths") for p in previous_raw)
    all_paths = (path, *previous)
    if len(set(all_paths)) != len(all_paths):
        raise ManifestError(f"{where}: duplicate entries in path and previous_paths")
    return Project(
        name=name,
        path=path,
        previous_paths=previous,
        description=_str(raw, "description", where, "") or "",
        approved=_sha(raw, "approved", where),
        allow_rewrite_of=_sha(raw, "allow_rewrite_of", where),
    )
