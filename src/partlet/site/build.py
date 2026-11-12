"""Construct public page models from exported snapshots and durable records."""

import posixpath
import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from markupsafe import Markup

from partlet.archive import ARCHIVE_FORMATS
from partlet.site import urls
from partlet.site.highlight import highlight_file
from partlet.site.links import Linker
from partlet.site.markdown import render_markdown
from partlet.site.models import (
    Archive,
    BlobPage,
    Breadcrumb,
    Entry,
    IndexPage,
    Project,
    TreePage,
)
from partlet.site.tree import FileEntry, is_viewable

README_NAMES = ("readme.md", "readme.markdown", "readme", "readme.txt", "readme.rst")
MARKDOWN_SUFFIXES = (".md", ".markdown")


def build_project(
    name: str, description: str, revision: str, base_url: str, updated_at: str
) -> Project:
    """Use the exported tip and its %cI committer time, never source identity."""
    if not all(
        isinstance(v, str) for v in (name, description, revision, base_url, updated_at)
    ):
        raise ValueError("project public fields must be strings")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", name) or name in (".", ".."):
        raise ValueError("invalid public project name")
    if not revision:
        raise ValueError("exported revision must not be empty")
    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", updated_at
    ):
        raise ValueError(
            "updated_at must be a Git ISO timestamp with explicit timezone"
        )
    try:
        datetime.fromisoformat(updated_at)
        if not updated_at.endswith("Z") and int(updated_at[-2:]) > 59:
            raise ValueError("invalid timezone minutes")
    except ValueError as exc:
        raise ValueError("invalid updated_at timestamp") from exc
    return Project(
        name,
        description,
        revision,
        updated_at,
        urls.tree_url(name, ""),
        urls.clone_url(base_url, name),
        tuple(Archive(fmt, urls.archive_url(name, fmt)) for fmt in ARCHIVE_FORMATS),
    )


def project_from_record(base_url: str, record: Mapping[str, object]) -> Project:
    # Explicit projection: current may also contain private build-management data.
    return build_project(
        record["name"],
        record["description"],
        record["tip"],
        base_url,
        record["updated"],
    )


def build_index(base_url: str, records: Sequence[Mapping[str, object]]) -> IndexPage:
    return IndexPage(
        tuple(
            sorted(
                (project_from_record(base_url, r) for r in records),
                key=lambda p: p.name,
            )
        )
    )


def _directories(
    entries: list[FileEntry],
) -> dict[str, tuple[set[str], list[FileEntry]]]:
    dirs: dict[str, tuple[set[str], list[FileEntry]]] = {"": (set(), [])}
    for entry in entries:
        parent = entry.parent
        dirs.setdefault(parent, (set(), []))[1].append(entry)
        while parent:
            grandparent = posixpath.dirname(parent)
            dirs.setdefault(grandparent, (set(), []))[0].add(parent)
            dirs.setdefault(parent, (set(), []))
            parent = grandparent
    return dirs


def _crumbs(project: str, directory: str) -> tuple[Breadcrumb, ...]:
    crumbs = [Breadcrumb(project, urls.tree_url(project, ""))]
    if directory:
        parts = directory.split("/")
        for i, part in enumerate(parts):
            crumbs.append(
                Breadcrumb(part, urls.tree_url(project, "/".join(parts[: i + 1])))
            )
    return tuple(crumbs)


def _readme_html(
    files: list[FileEntry], directory: str, linker: Linker
) -> Markup | None:
    by_name = {f.name.lower(): f for f in files if is_viewable(f)}
    for candidate in README_NAMES:
        entry = by_name.get(candidate)
        if entry is None:
            continue
        text = entry.data.decode("utf-8")
        if entry.name.lower().endswith(MARKDOWN_SUFFIXES):
            return Markup(render_markdown(text, directory, linker))
        return Markup("<pre>{}</pre>").format(text)
    return None


def _entry(project: Project, entry: FileEntry) -> Entry:
    return Entry(
        entry.name,
        entry.path,
        "symlink" if entry.is_symlink else "file",
        urls.blob_url(project.name, entry.path),
        entry.size,
    )


def build_pages(
    project: Project, entries: list[FileEntry]
) -> tuple[TreePage | BlobPage, ...]:
    """Construct one snapshot, ordered directories first, then blobs by path."""
    entries = sorted(entries, key=lambda e: e.path)
    dirs = _directories(entries)
    linker = Linker(project.name, {e.path for e in entries}, set(dirs))
    pages: list[TreePage | BlobPage] = []
    for directory, (subdirs, files) in sorted(dirs.items()):
        children = tuple(
            Entry(
                posixpath.basename(d),
                d,
                "directory",
                urls.tree_url(project.name, d),
                None,
            )
            for d in sorted(subdirs)
        ) + tuple(_entry(project, f) for f in sorted(files, key=lambda f: f.name))
        pages.append(
            TreePage(
                project,
                directory,
                _crumbs(project.name, directory),
                children,
                _readme_html(files, directory, linker),
            )
        )
    for entry in entries:
        viewable = is_viewable(entry)
        pages.append(
            BlobPage(
                project,
                _entry(project, entry),
                _crumbs(project.name, entry.parent),
                urls.raw_url(project.name, entry.path),
                entry.data.decode("utf-8", "replace") if entry.is_symlink else None,
                "symlink"
                if entry.is_symlink
                else "source"
                if viewable
                else "unavailable",
                Markup(highlight_file(entry.path, entry.data.decode("utf-8")))
                if viewable
                else None,
            )
        )
    return tuple(pages)
