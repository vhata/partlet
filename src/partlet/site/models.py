"""Version-1 public rendering records; no storage or repository objects."""

from dataclasses import dataclass, field
from typing import Literal

from markupsafe import Markup


@dataclass(frozen=True)
class Archive:
    format: str
    url: str


@dataclass(frozen=True)
class SiteIdentity:
    name: str
    tagline: str = ""


@dataclass(frozen=True)
class Project:
    name: str
    description: str
    revision: str
    updated_at: str
    url: str
    clone_url: str
    archives: tuple[Archive, ...]


@dataclass(frozen=True)
class Breadcrumb:
    label: str
    url: str


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    kind: Literal["directory", "file", "symlink"]
    url: str
    size_bytes: int | None


@dataclass(frozen=True)
class IndexPage:
    projects: tuple[Project, ...]
    intro_html: Markup | None = None
    identity: SiteIdentity = field(default_factory=lambda: SiteIdentity("Projects"))
    output_version: Literal[1] = field(default=1, init=False)
    kind: Literal["index"] = field(default="index", init=False)


@dataclass(frozen=True)
class TreePage:
    project: Project
    path: str
    breadcrumbs: tuple[Breadcrumb, ...]
    entries: tuple[Entry, ...]
    readme_html: Markup | None
    identity: SiteIdentity = field(default_factory=lambda: SiteIdentity("Projects"))
    output_version: Literal[1] = field(default=1, init=False)
    kind: Literal["tree"] = field(default="tree", init=False)


@dataclass(frozen=True)
class BlobPage:
    project: Project
    entry: Entry
    breadcrumbs: tuple[Breadcrumb, ...]
    raw_url: str
    symlink_target: str | None
    content_state: Literal["source", "symlink", "unavailable"]
    source_html: Markup | None
    identity: SiteIdentity = field(default_factory=lambda: SiteIdentity("Projects"))
    output_version: Literal[1] = field(default=1, init=False)
    kind: Literal["blob"] = field(default="blob", init=False)
