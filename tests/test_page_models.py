from dataclasses import asdict, fields, replace

import pytest
from markupsafe import Markup

from partlet.site.build import build_index, build_pages, build_project
from partlet.site.models import BlobPage, Project, TreePage
from partlet.site.render import render_page
from partlet.site.tree import SIZE_CAP, FileEntry

STAMP = "2026-11-05T09:08:07-07:30"


def project():
    return build_project(
        "foo", "<b>description</b>", "a" * 64, "https://example.com", STAMP
    )


def test_public_allowlist_and_index_order():
    records = [
        {
            "name": name,
            "description": "public",
            "tip": "a" * 64,
            "updated": STAMP,
            "source": "private/path",
            "approved": "secret",
            "build": "internal",
        }
        for name in ("z", "a")
    ]
    page = build_index("https://example.com", records)
    assert (page.kind, page.output_version) == ("index", 1)
    assert [p.name for p in page.projects] == ["a", "z"]
    assert {f.name for f in fields(Project)} == {
        "name",
        "description",
        "revision",
        "updated_at",
        "url",
        "clone_url",
        "archives",
    }
    assert "private" not in repr(asdict(page))
    assert page.projects[0].revision == "a" * 64
    assert page.projects[0].updated_at == STAMP
    assert page.projects[0].clone_url == "https://example.com/a"


@pytest.mark.parametrize(
    "timestamp",
    [
        "",
        "2026",
        "2026-11-05",
        "2026-11-05T09:00:00",
        "2026-02-30T00:00:00+00:00",
        "2026-11-05T09:00:00+00:60",
        "2026-11-05T09:00:00+24:00",
    ],
)
def test_invalid_timestamps_rejected(timestamp):
    with pytest.raises(ValueError, match="timestamp|updated_at"):
        build_project("foo", "", "opaque-revision", "https://example.com", timestamp)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "//evil.test",
        "https://user:secret@example.com",
        "https://example.com/#fragment",
        "https://example.com/?token=secret",
        "https://example.com\\@evil.test",
    ],
)
def test_unsafe_clone_urls_rejected(url):
    with pytest.raises(ValueError, match="base_url"):
        build_project("foo", "", "opaque-revision", url, STAMP)


def test_snapshot_order_kinds_bytes_and_content_states():
    entries = [
        FileEntry("z", b"\xfftarget", True),
        FileEntry("docs/a #é", b"hi"),
        FileEntry("empty", b""),
        FileEntry("binary", b"\0"),
        FileEntry("large", b"x" * (SIZE_CAP + 1)),
    ]
    pages = build_pages(project(), entries)
    assert pages == build_pages(project(), list(reversed(entries)))
    root = pages[0]
    assert isinstance(root, TreePage)
    assert root.path == "" and root.readme_html is None
    assert [(e.name, e.kind, e.size_bytes) for e in root.entries] == [
        ("docs", "directory", None),
        ("binary", "file", 1),
        ("empty", "file", 0),
        ("large", "file", SIZE_CAP + 1),
        ("z", "symlink", 7),
    ]
    blobs = {p.entry.path: p for p in pages if isinstance(p, BlobPage)}
    assert blobs["z"].content_state == "symlink"
    assert blobs["z"].symlink_target == "�target"
    assert blobs["z"].source_html is None
    assert (
        blobs["binary"].content_state == blobs["large"].content_state == "unavailable"
    )
    assert blobs["empty"].content_state == "source"
    assert isinstance(blobs["empty"].source_html, Markup)
    assert blobs["docs/a #é"].raw_url == "/foo/raw/docs/a%20%23%C3%A9"
    assert blobs["docs/a #é"].breadcrumbs[-1].label == "docs"
    assert all(p.output_version == 1 for p in pages)


def test_only_renderer_owned_html_is_trusted():
    root = build_pages(project(), [FileEntry("README", b"<script>bad</script>")])[0]
    assert isinstance(root.readme_html, Markup)
    html = render_page(root)
    assert b"<script>" not in html and b"&lt;script&gt;" in html
    assert b"&lt;b&gt;description&lt;/b&gt;" in html
    injected = replace(root, readme_html="<script>bad</script>")
    assert b"<script>" not in render_page(injected)


def test_git_utc_designator_is_preserved():
    stamp = "2026-11-05T09:00:00Z"
    assert (
        build_project("foo", "", "opaque", "https://example.com", stamp).updated_at
        == stamp
    )


def test_exported_snapshot_provenance(mono, tmp_path):
    from partlet.export import export_project
    from partlet.gitutil import git_out
    from partlet.manifest import Project as ExportProject
    from partlet.site.tree import read_tree

    mono.write("foo/a.txt", "exported\n")
    mono.write("private/secret.txt", "never public\n")
    source_tip = mono.commit("snapshot")
    exported = tmp_path / "export.git"
    tip = export_project(mono.path, "main", ExportProject("foo", "foo"), exported)
    stamp = git_out("show", "-s", "--format=%cI", tip, cwd=exported)
    info = build_project("foo", "", tip, "https://example.com", stamp)
    pages = build_pages(info, read_tree(exported, tip))
    assert tip != source_tip
    assert all(page.project.revision == tip for page in pages)
    assert all(page.project.updated_at == stamp for page in pages)
    assert [entry.path for entry in pages[0].entries] == ["a.txt"]
    assert "secret" not in repr(pages)


def test_source_free_unpublish_rebuilds_surviving_public_model(tmp_path):
    import json

    from partlet.manifest import Site, ThemeConfig
    from partlet.publish import unpublish_project, write_site_index
    from partlet.site.themes import resolve_theme
    from partlet.store import LocalStore

    store = LocalStore(tmp_path / "objects")
    site = Site(source="s", branch="main", base_url="https://example.com")
    for name in ("keep", "remove"):
        store.put(
            f"s/p/{name}/current",
            json.dumps(
                {
                    "name": name,
                    "description": "<b>public</b>",
                    "tip": "a" * 64,
                    "updated": STAMP,
                    "build": "internal",
                    "source": "private/path",
                }
            ).encode(),
        )
    write_site_index(store, site, resolve_theme(ThemeConfig(name="paper")))
    # No source checkout exists; this nonexistent theme cannot be resolved.
    site = replace(site, theme=ThemeConfig(name=None, path="missing"))
    unpublish_project(store, site, "remove")
    records = json.loads(store.get("s/index.json"))
    assert [r["name"] for r in records] == ["keep"]
    model = build_index(site.base_url, records)
    assert model.projects[0].updated_at == STAMP
    assert model.projects[0].revision == "a" * 64
    page = store.get("s/index.html")
    assert b'href="/keep"' in page and b'href="/remove"' not in page
    assert b"private/path" not in page and b"internal" not in page
    assert b"&lt;b&gt;public&lt;/b&gt;" in page
