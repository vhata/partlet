"""Parse the output contract independently of visual layout and whitespace."""

from html.parser import HTMLParser

from partlet.site.build import build_project
from partlet.site.render import render_project, render_site_index
from partlet.site.tree import SIZE_CAP, FileEntry


class Document(HTMLParser):
    def __init__(self, data):
        super().__init__()
        self.elements = []
        self.feed(data.decode())

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]


def test_every_page_exposes_public_values_and_accessible_structure():
    stamp = "2026-11-05T09:07:03-07:00"
    revision = "exported-opaque-" + "ab" * 32
    project = build_project("foo", '<script>"&', revision, "https://example.com", stamp)
    unusual = "docs/" + "long-" * 20 + 'é <"&?#.py'
    entries = [
        FileEntry(
            "README.md", b"# Documentation\n\n[Source](code.py)\n<script>bad</script>"
        ),
        FileEntry("code.py", b"print('hello')\nprint('again')\n"),
        FileEntry("docs/README", b"Plain <script>content</script>"),
        FileEntry(unusual, b"x\n"),
        FileEntry("link", b'../<private>&"', True),
        FileEntry("binary", b"\0\xff"),
        FileEntry("oversized", b"x" * (SIZE_CAP + 1)),
        FileEntry("empty", b""),
    ]
    pages = render_project(project, entries)
    pages["site-index"] = render_site_index(
        "https://example.com",
        [
            {
                "name": project.name,
                "description": project.description,
                "tip": revision,
                "updated": stamp,
            }
        ],
    )
    for key, html in pages.items():
        if key.startswith("raw/"):
            continue
        doc = Document(html)
        kind = (
            "index"
            if key == "site-index"
            else "blob"
            if key.startswith("blob/")
            else "tree"
        )
        assert doc.find("html")[0]["data-partlet-page"] == kind
        assert doc.find("html")[0]["data-partlet-output-version"] == "1"
        assert len(doc.find("main")) == 1
        assert doc.find("h1")
        assert not doc.find("script")
        assert any(a.get("data-partlet-project") == "foo" for _, a in doc.elements)
        assert any(a.get("data-partlet-revision") == revision for a in doc.find("code"))
        assert doc.find("time")[0]["datetime"] == stamp
        for table in doc.find("table"):
            assert table.get("aria-label")
            assert all(a.get("scope") == "col" for a in doc.find("th"))
            assert doc.find("th")
        if kind != "index":
            assert doc.find("nav")[0]["aria-label"] == "Breadcrumb"
        if kind == "blob":
            entry = next(e for e in entries if e.path == key[5:])
            attrs = next(a for _, a in doc.elements if "data-partlet-path" in a)
            assert attrs["data-partlet-path"] == entry.path
            assert attrs["data-partlet-entry-kind"] == (
                "symlink" if entry.is_symlink else "file"
            )
            assert doc.find("data")[0]["value"] == str(len(entry.data))
            assert any("/raw/" in a.get("href", "") for a in doc.find("a"))
    root = Document(pages["index.html"])
    assert any(
        a.get("data-partlet-entry-kind") == "directory"
        and a["data-partlet-path"] == "docs"
        for a in root.find("tr")
    )
    source = Document(pages["blob/code.py"])
    assert any(a.get("id") == "L-2" for a in source.find("a"))
    assert b'href="/foo/blob/code.py"' in pages["index.html"]
    assert (
        b"Plain &lt;script&gt;content&lt;/script&gt;" in pages["tree/docs/index.html"]
    )
    assert pages["raw/link"] == b'../<private>&"'
