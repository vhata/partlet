from partlet.site.render import (
    ProjectInfo,
    render_project,
    render_site_index,
    site_stylesheet,
)
from partlet.site.tree import SIZE_CAP, FileEntry

INFO = ProjectInfo(
    "foo", "Foo tool", "a" * 40, "https://partlet.example", "2026-01-01T00:00:00+00:00"
)


def render(entries):
    return {
        k: v.decode("utf-8") if not k.startswith("raw/") else v
        for k, v in render_project(INFO, entries).items()
    }


def test_keys_for_every_file_and_directory():
    pages = render(
        [
            FileEntry("README.md", b"# Hello\n"),
            FileEntry("src/main.py", b"print(1)\n"),
            FileEntry("src/deep/x.txt", b"x\n"),
        ]
    )
    assert set(pages) == {
        "index.html",
        "tree/src/index.html",
        "tree/src/deep/index.html",
        "blob/README.md",
        "blob/src/main.py",
        "blob/src/deep/x.txt",
        "raw/README.md",
        "raw/src/main.py",
        "raw/src/deep/x.txt",
    }
    assert pages["raw/src/main.py"] == b"print(1)\n"


def test_project_page_has_readme_clone_url_and_downloads():
    page = render([FileEntry("README.md", b"# Hello\n"), FileEntry("a.txt", b"a")])[
        "index.html"
    ]
    assert "<h1>Hello</h1>" in page
    assert "git clone https://partlet.example/foo" in page
    assert 'href="/foo/archive/foo.tar.gz"' in page
    assert 'href="/foo/archive/foo.zip"' in page
    assert 'href="/foo/blob/a.txt"' in page
    assert "Foo tool" in page
    assert 'href="/_partlet/style.css"' in page
    assert "<script" not in page


def test_subdirectory_readme_links_resolve_from_that_directory():
    pages = render(
        [FileEntry("docs/README.md", b"[up](../a.txt)\n"), FileEntry("a.txt", b"a")]
    )
    assert 'href="/foo/blob/a.txt"' in pages["tree/docs/index.html"]


def test_file_page_highlights_and_links_raw():
    page = render([FileEntry("src/main.py", b"def f(): pass\n")])["blob/src/main.py"]
    assert 'class="hl' in page
    assert 'href="/foo/raw/src/main.py"' in page
    assert 'href="/foo/tree/src"' in page  # breadcrumb


def test_binary_and_large_files_get_download_only():
    pages = render(
        [FileEntry("a.bin", b"\x00\x01"), FileEntry("big.txt", b"x" * (SIZE_CAP + 1))]
    )
    for key in ("blob/a.bin", "blob/big.txt"):
        assert 'class="hl' not in pages[key]
        assert "raw" in pages[key] and "not shown" in pages[key]


def test_special_file_names_are_encoded():
    pages = render([FileEntry("my dir/#1 ?é%.txt", b"x\n")])
    assert "blob/my dir/#1 ?é%.txt" in pages
    assert "raw/my dir/#1 ?é%.txt" in pages
    assert 'href="/foo/tree/my%20dir"' in pages["index.html"]
    assert (
        'href="/foo/blob/my%20dir/%231%20%3F%C3%A9%25.txt"'
        in pages["tree/my dir/index.html"]
    )
    assert "#1 ?é%.txt" in pages["tree/my dir/index.html"]  # visible label unencoded


def test_symlinks_are_shown_not_followed():
    pages = render([FileEntry("link", b"../../etc/passwd", is_symlink=True)])
    assert "Symbolic link to" in pages["blob/link"]
    assert "../../etc/passwd" in pages["blob/link"]
    assert pages["raw/link"] == b"../../etc/passwd"


def test_html_in_names_and_content_is_escaped():
    pages = render([FileEntry("<b>.txt", b"<script>x</script>\n")])
    assert "<b>.txt" not in pages["index.html"]
    assert "<script>x" not in pages["blob/<b>.txt"]


def test_plain_readme_symlink_target_and_description_are_escaped():
    info = ProjectInfo(
        "foo", "<script>d</script>", "a" * 40, "https://partlet.example", "2026"
    )
    entries = [
        FileEntry("README", b"<script>x</script>\n"),
        FileEntry("link", b"<b>target", is_symlink=True),
    ]
    pages = {k: v.decode("utf-8") for k, v in render_project(info, entries).items()}
    index = pages["index.html"]
    assert "<script>" not in index
    assert "&lt;script&gt;x&lt;/script&gt;" in index
    assert "&lt;script&gt;d&lt;/script&gt;" in index
    assert "<b>target" not in pages["blob/link"]
    assert "&lt;b&gt;target" in pages["blob/link"]
    listing = render_site_index(
        info.base_url,
        [
            {
                "name": "foo",
                "description": info.description,
                "tip": info.tip,
                "updated": "",
            }
        ],
    ).decode()
    assert "<script>" not in listing
    assert "&lt;script&gt;d&lt;/script&gt;" in listing


def test_site_index_lists_projects():
    page = render_site_index(
        "https://partlet.example",
        [
            {
                "name": "foo",
                "description": "Foo tool",
                "tip": "a" * 40,
                "updated": "2026-01-01T00:00:00+00:00",
            },
        ],
    ).decode()
    assert 'href="/foo"' in page and "Foo tool" in page
    assert "aaaaaaaaaaaa" in page


def test_stylesheet_includes_pygments():
    assert b".hl" in site_stylesheet()
