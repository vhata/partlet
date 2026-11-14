from partlet.manifest import ThemeConfig, parse_manifest
from partlet.site.build import build_project
from partlet.site.render import (
    render_project,
    render_site_index,
    site_stylesheet,
)
from partlet.site.themes import resolve_theme
from partlet.site.tree import SIZE_CAP, FileEntry
from partlet.store import LocalStore

INFO = build_project(
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
        "tree/src/children/deep/index.html",
        "blob/README.md",
        "blob/src/main.py",
        "blob/src/deep/x.txt",
        "raw/README.md",
        "raw/src/main.py",
        "raw/src/deep/x.txt",
    }
    assert pages["raw/src/main.py"] == b"print(1)\n"


def test_directory_pages_do_not_collide_with_descendants(tmp_path):
    pages = render_project(
        INFO,
        [
            FileEntry("docs/index.html/index.html/leaf.txt", b"nested\n"),
            FileEntry("docs/children/leaf.txt", b"namespace\n"),
            FileEntry("index.html/leaf.txt", b"root\n"),
        ],
    )
    store = LocalStore(tmp_path)
    for key, data in pages.items():
        store.put(key, data)
    assert all(store.get(key) == data for key, data in pages.items())
    assert b'href="/foo/tree/docs/index.html"' in store.get("tree/docs/index.html")
    assert b'href="/foo/tree/docs/index.html/index.html"' in store.get(
        "tree/docs/children/index.html/index.html"
    )
    assert b"leaf.txt" in store.get(
        "tree/docs/children/index.html/children/index.html/index.html"
    )
    assert b"leaf.txt" in store.get("tree/docs/children/children/index.html")
    assert b"leaf.txt" in store.get("tree/index.html/index.html")


def test_nested_directory_key_keeps_original_name_segments():
    pages = render([FileEntry("docs/a!'()*~%é/leaf.txt", b"leaf\n")])
    assert (
        'href="/foo/tree/docs/a%21%27%28%29%2A~%25%C3%A9"'
        in pages["tree/docs/index.html"]
    )
    assert "leaf.txt" in pages["tree/docs/children/a!'()*~%é/index.html"]


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
    info = build_project(
        "foo",
        "<script>d</script>",
        "a" * 40,
        "https://partlet.example",
        "2026-01-01T00:00:00+00:00",
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
        "https://partlet.example",
        [
            {
                "name": "foo",
                "description": info.description,
                "tip": info.revision,
                "updated": "2026-01-01T00:00:00+00:00",
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


def test_theme_applies_to_every_rendered_page_and_site_index():
    theme = resolve_theme(ThemeConfig(name="paper", mode="dark"))
    pages = render_project(
        INFO,
        [
            FileEntry("README.md", b"# Read me\n"),
            FileEntry("src/example.py", b"print('hello')\n"),
        ],
        theme,
    )
    index = render_site_index(
        "https://partlet.example",
        [
            {
                "name": INFO.name,
                "description": INFO.description,
                "tip": INFO.revision,
                "updated": INFO.updated_at,
            }
        ],
        theme,
    )
    # Index timestamps need a wrapping hook, not the nowrap file-size hook.
    assert b'class="listing projects"' in index
    assert (
        f'<time datetime="{INFO.updated_at}" title="{INFO.updated_at}">2026-01-01</time>'.encode()
        in index
    )
    assert b'class="size"' not in index
    for data in [
        index,
        *(data for path, data in pages.items() if not path.startswith("raw/")),
    ]:
        assert f'href="{theme.stylesheet_url}"'.encode() in data
        assert b'data-theme="paper" data-mode="dark"' in data
        assert b"/_partlet/style.css" not in data
        assert b"<script" not in data
    assert pages["raw/src/example.py"] == b"print('hello')\n"


def test_default_renderer_uses_shared_stylesheet():
    assert b'href="/_partlet/style.css"' in render_site_index(
        "https://partlet.example", []
    )
    assert b'data-mode="auto"' in render_site_index("https://partlet.example", [])


def test_manifest_without_theme_gets_default_layout_and_color_preference():
    manifest = parse_manifest("""[site]
source = "s"
base_url = "https://partlet.example"
[projects.foo]
path = "foo"
""")
    theme = resolve_theme(manifest.site.theme)
    assert (theme.name, theme.mode) == ("classic", "auto")
    page = render_project(INFO, [FileEntry("README.md", b"# Hello\n")], theme)[
        "index.html"
    ]
    assert b'data-theme="classic" data-mode="auto"' in page
    assert theme.stylesheet_url.encode() in page
    assert b'aria-labelledby="clone-heading"' in page
    assert b'aria-label="Files and directories"' in page
    assert b'aria-label="README"' in page


def test_page_landmarks_and_skip_link_work_on_index_tree_and_file():
    pages = render_project(INFO, [FileEntry("src/main.py", b"print(1)\n")])
    for page in (
        render_site_index("https://partlet.example", []),
        pages["index.html"],
        pages["tree/src/index.html"],
        pages["blob/src/main.py"],
    ):
        assert b'href="#content">Skip to content</a>' in page
        assert b'<main id="content" tabindex="-1"' in page
        assert b'<header class="top">' in page
        assert b'<footer class="site-footer">' in page
    assert b"<h1>foo</h1>" in pages["index.html"]
    assert b"<h1>src</h1>" in pages["tree/src/index.html"]
    assert b"<h1>main.py</h1>" in pages["blob/src/main.py"]
    assert b'aria-label="Breadcrumb"' in pages["blob/src/main.py"]
    assert b'<span aria-current="page">main.py</span>' in pages["blob/src/main.py"]


def test_empty_index_and_repository_explain_absent_content():
    index = render_site_index("https://partlet.example", [])
    assert b"No projects published yet" in index
    assert b"0 projects" in index
    assert b'<table class="listing projects"' not in index
    project = render_project(INFO, [])["index.html"]
    assert b"This repository has no files at this revision." in project
    assert b"0 entries" in project
    assert b'<table class="listing"' not in project
