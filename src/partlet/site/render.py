"""Turn an export tip into static pages."""

from __future__ import annotations

from dataclasses import replace

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from partlet.site.build import build_index, build_pages
from partlet.site.models import BlobPage, IndexPage, Project, SiteIdentity, TreePage
from partlet.site.themes import ThemePresentation, resolve_theme
from partlet.site.tree import FileEntry

_env = Environment(
    loader=PackageLoader("partlet.site", "templates"),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


def _human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


_env.filters["human_size"] = _human_size


def render_page(
    page: IndexPage | TreePage | BlobPage, theme: ThemePresentation | None = None
) -> bytes:
    return (
        _env.get_template(f"{page.kind}.html")
        .render(page=page, theme=theme)
        .encode("utf-8")
    )


def render_project(
    project: Project,
    entries: list[FileEntry],
    theme: ThemePresentation | None = None,
    identity: SiteIdentity | None = None,
) -> dict[str, bytes]:
    out = {}
    for page in build_pages(project, entries):
        if identity is not None:
            page = replace(page, identity=identity)
        if isinstance(page, TreePage):
            tree_path = "/children/".join(page.path.split("/"))
            key = "index.html" if not page.path else f"tree/{tree_path}/index.html"
        else:
            key = f"blob/{page.entry.path}"
        out[key] = render_page(page, theme)
    for entry in sorted(entries, key=lambda e: e.path):
        out[f"raw/{entry.path}"] = entry.data
    return out


def render_site_index(
    base_url: str,
    projects: list[dict],
    theme: ThemePresentation | None = None,
    identity: SiteIdentity | None = None,
    intro_html: Markup | None = None,
) -> bytes:
    return render_page(
        replace(build_index(base_url, projects, identity), intro_html=intro_html), theme
    )


def site_stylesheet() -> bytes:
    """Default presentation for unthemed rendering and Worker error pages."""
    return resolve_theme().resources[0].data
