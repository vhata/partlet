"""Load and validate partlet.toml."""

from __future__ import annotations

import os
import re
import stat
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")

SITE_KEYS = {
    "source",
    "branch",
    "base_url",
    "name",
    "tagline",
    "readme",
    "mailmap",
    "theme",
}
PROJECT_KEYS = {"path", "previous_paths", "description", "approved", "allow_rewrite_of"}
THEME_NAMES = ("classic", "paper", "terminal")
THEME_MODES = ("auto", "light", "dark")


class ManifestError(Exception):
    """partlet.toml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class ThemeConfig:
    name: str | None = "classic"
    path: str | None = None
    mode: str = "auto"


@dataclass(frozen=True)
class Site:
    source: str
    branch: str
    base_url: str
    name: str = ""
    tagline: str = ""
    readme: str | None = None
    mailmap: str | None = None
    theme: ThemeConfig = field(default_factory=ThemeConfig)

    def __post_init__(self) -> None:
        if not self.name:
            from urllib.parse import urlsplit

            object.__setattr__(
                self, "name", urlsplit(self.base_url).hostname or self.base_url
            )


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


def set_project_fields(
    path: Path,
    name: str,
    fields: dict[str, str],
    *,
    expected_text: str | None = None,
) -> None:
    """Atomically edit a project while preserving TOML comments and layout.

    ``expected_text`` lets an interactive review refuse to approve a manifest
    that changed while its report or approval question was on screen.
    """
    import tomlkit

    tmp: Path | None = None
    try:
        original = path.read_bytes().decode("utf-8")
        if expected_text is not None and original != expected_text:
            raise ManifestError(
                "manifest changed during review; run partlet review again"
            )
        manifest = parse_manifest(original)
        if name not in manifest.projects:
            raise ManifestError(f"project {name!r} is not in {path}")
        doc = tomlkit.parse(original)
        table = doc["projects"][name]
        for key, value in fields.items():
            if key not in PROJECT_KEYS:
                raise ManifestError(f"{key!r} is not a project key")
            if not isinstance(value, str):
                raise ManifestError(f"{key!r} must be a string")
            table[key] = value
        text = tomlkit.dumps(doc)
        parse_manifest(text)
        mode = stat.S_IMODE(path.stat().st_mode)
        fd, tmpname = tempfile.mkstemp(prefix=f".{path.name}.partlet-", dir=path.parent)
        tmp = Path(tmpname)
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(text.encode("utf-8"))
        # Recheck after constructing the edit, before replacing the original.
        if path.read_bytes().decode("utf-8") != original:
            raise ManifestError(
                "manifest changed during edit; run partlet review again"
            )
        tmp.replace(path)
    except (OSError, UnicodeError, tomlkit.exceptions.ParseError) as exc:
        raise ManifestError(f"cannot edit {path}: {exc}") from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


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
    if ":" in value:
        raise ManifestError(
            f"{where}: path {value!r} contains a colon; use project paths without ':'"
        )
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
        name=_str(raw, "name", "site", _site_name(base_url)) or _site_name(base_url),
        tagline=_str(raw, "tagline", "site", "") or "",
        readme=_readme_path(raw),
        mailmap=_str(raw, "mailmap", "site"),
        theme=_parse_theme(raw.get("theme", {})),
    )


def _site_name(base_url: str) -> str:
    from urllib.parse import urlsplit

    return urlsplit(base_url).hostname or base_url.rstrip("/")


def _parse_theme(raw: Any) -> ThemeConfig:
    where = "site.theme"
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be a table")
    _check_keys(raw, {"name", "path", "mode"}, where)
    if "name" in raw and "path" in raw:
        raise ManifestError(f"{where}: name and path are mutually exclusive")
    name = _str(raw, "name", where, None if "path" in raw else "classic")
    path = _str(raw, "path", where)
    mode = _str(raw, "mode", where, "auto")
    if name is not None and name not in THEME_NAMES:
        raise ManifestError(f"{where}.name must be one of {', '.join(THEME_NAMES)}")
    if mode not in THEME_MODES:
        raise ManifestError(f"{where}.mode must be one of {', '.join(THEME_MODES)}")
    # Unlike historical project paths, theme paths cannot start with /.
    if path is not None and (
        not path
        or any(part in ("", ".", "..") for part in path.split("/"))
        or any(char in path for char in "\\:\0")
    ):
        raise ManifestError(
            f"{where}.path must be a relative directory without traversal"
        )
    return ThemeConfig(name=name, path=path, mode=mode)


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


def _readme_path(raw: dict) -> str | None:
    value = _str(raw, "readme", "site")
    if value is not None and (
        not value
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or any(p in ("", ".", "..") for p in value.split("/"))
        or not value.lower().endswith((".md", ".markdown"))
    ):
        raise ManifestError(
            "site.readme must be a source-repository-relative Markdown file without traversal"
        )
    return value
