"""Turn an export tip into static pages."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from importlib import resources

from jinja2 import Environment, PackageLoader, select_autoescape

from partlet.archive import ARCHIVE_FORMATS
from partlet.site import urls
from partlet.site.highlight import highlight_file, pygments_css
from partlet.site.links import Linker
from partlet.site.markdown import render_markdown
from partlet.site.tree import FileEntry, is_viewable

README_NAMES = ("readme.md", "readme.markdown", "readme", "readme.txt", "readme.rst")
MARKDOWN_SUFFIXES = (".md", ".markdown")

_env = Environment(
    loader=PackageLoader("partlet.site", "templates"),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    description: str
    tip: str
    base_url: str
    updated: str


def _human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


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


def _crumbs(project: str, directory: str) -> list[tuple[str, str]]:
    crumbs = [(project, urls.tree_url(project, ""))]
    if directory:
        parts = directory.split("/")
        for i, part in enumerate(parts):
            crumbs.append((part, urls.tree_url(project, "/".join(parts[: i + 1]))))
    return crumbs


def _readme_html(files: list[FileEntry], directory: str, linker: Linker) -> str | None:
    by_name = {f.name.lower(): f for f in files if is_viewable(f)}
    for candidate in README_NAMES:
        entry = by_name.get(candidate)
        if entry is None:
            continue
        text = entry.data.decode("utf-8")
        if entry.name.lower().endswith(MARKDOWN_SUFFIXES):
            return render_markdown(text, directory, linker)
        return _env.from_string("<pre>{{ text }}</pre>").render(text=text)
    return None


def render_project(info: ProjectInfo, entries: list[FileEntry]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    dirs = _directories(entries)
    linker = Linker(info.name, {e.path for e in entries}, set(dirs))
    tree_tpl = _env.get_template("tree.html")
    blob_tpl = _env.get_template("blob.html")
    archives = [(fmt, urls.archive_url(info.name, fmt)) for fmt in ARCHIVE_FORMATS]

    for directory, (subdirs, files) in dirs.items():
        html = tree_tpl.render(
            project=info,
            directory=directory,
            crumbs=_crumbs(info.name, directory),
            clone_url=f"{info.base_url}/{info.name}",
            archives=archives,
            subdirs=[
                (posixpath.basename(d), urls.tree_url(info.name, d))
                for d in sorted(subdirs)
            ],
            files=[
                (f.name, urls.blob_url(info.name, f.path), _human_size(f.size))
                for f in sorted(files, key=lambda f: f.name)
            ],
            readme_html=_readme_html(files, directory, linker),
        )
        # Each node holds index.html and a separate namespace for its children.
        # Repository directories named index.html (or children) stay ordinary
        # path components without becoming ancestors of a stored page file.
        tree_path = "/children/".join(directory.split("/"))
        key = "index.html" if not directory else f"tree/{tree_path}/index.html"
        out[key] = html.encode("utf-8")

    for entry in entries:
        body = (
            highlight_file(entry.path, entry.data.decode("utf-8"))
            if is_viewable(entry)
            else None
        )
        html = blob_tpl.render(
            project=info,
            path=entry.path,
            name=entry.name,
            crumbs=_crumbs(info.name, entry.parent),
            size=_human_size(entry.size),
            raw_url=urls.raw_url(info.name, entry.path),
            symlink_target=entry.data.decode("utf-8", "replace")
            if entry.is_symlink
            else None,
            body_html=body,
        )
        out[f"blob/{entry.path}"] = html.encode("utf-8")
        out[f"raw/{entry.path}"] = entry.data
    return out


def render_site_index(base_url: str, projects: list[dict]) -> bytes:
    ordered = sorted(projects, key=lambda p: p["name"])
    return (
        _env.get_template("index.html")
        .render(base_url=base_url, projects=ordered)
        .encode("utf-8")
    )


def site_stylesheet() -> bytes:
    base = (
        resources.files("partlet.site")
        .joinpath("style.css")
        .read_text(encoding="utf-8")
    )
    return (base + "\n" + pygments_css() + "\n").encode("utf-8")
