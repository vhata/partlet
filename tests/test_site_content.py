import pytest

from partlet.export import export_project
from partlet.manifest import Project
from partlet.site import urls
from partlet.site.highlight import highlight_file, pygments_css
from partlet.site.links import Linker
from partlet.site.markdown import render_markdown
from partlet.site.render import ProjectInfo, render_project
from partlet.site.tree import (
    SIZE_CAP,
    FileEntry,
    TreeError,
    is_binary,
    is_viewable,
    read_tree,
)


def test_read_tree_reads_files_and_symlinks(mono, tmp_path):
    mono.write("foo/a.txt", "alpha\n")
    mono.write("foo/sub/b.bin", b"\x00\x01")
    mono.symlink("foo/link", "../../etc/passwd")
    mono.commit("c1")
    repo = tmp_path / "e.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)
    entries = read_tree(repo, tip)
    assert [e.path for e in entries] == ["a.txt", "link", "sub/b.bin"]
    assert entries[0].data == b"alpha\n" and not entries[0].is_symlink
    assert entries[1].is_symlink and entries[1].data == b"../../etc/passwd"
    assert entries[2].parent == "sub" and entries[2].name == "b.bin"


def test_binary_and_viewable():
    assert is_binary(b"a\x00b")
    assert is_binary(b"\xff\xfe\xfa")
    assert not is_binary("héllo".encode())
    assert is_viewable(FileEntry("a.txt", b"hi"))
    assert not is_viewable(FileEntry("a.txt", b"x" * (SIZE_CAP + 1)))
    assert not is_viewable(FileEntry("a.bin", b"\x00"))
    assert not is_viewable(FileEntry("l", b"target", is_symlink=True))


@pytest.mark.parametrize(
    "files",
    [
        {b"file-\xfe.txt": b"first", b"file-\xff.txt": b"second"},
        {b"dir-\xff/leaf.txt": b"nested"},
        {b"file-\xc0\xaf.txt": b"overlong encoding"},
    ],
)
def test_read_tree_rejects_non_utf8_paths(mono, files):
    tip = mono.commit_raw(files, "byte paths")
    with pytest.raises(TreeError) as exc:
        read_tree(mono.path, tip)
    assert "not valid UTF-8" in str(exc.value)
    assert repr(next(iter(files))) in str(exc.value)


def test_unicode_paths_keep_distinct_site_keys_and_links(mono):
    files = {"file-\ufffd.txt": b"replacement character", "dir/é.txt": b"accent"}
    tip = mono.commit_raw({p.encode(): data for p, data in files.items()}, "Unicode")
    entries = read_tree(mono.path, tip)
    assert {e.path: e.data for e in entries} == files
    pages = render_project(
        ProjectInfo("foo", "", tip, "https://example.com", ""), entries
    )
    for path, data in files.items():
        assert pages[f"raw/{path}"] == data
        assert urls.raw_url("foo", path).encode() in pages[f"blob/{path}"]
        parent = path.rpartition("/")[0]
        tree_key = f"tree/{parent}/index.html" if parent else "index.html"
        assert urls.blob_url("foo", path).encode() in pages[tree_key]


def test_urls_percent_encode():
    assert urls.tree_url("foo", "") == "/foo"
    assert urls.tree_url("foo", "a b") == "/foo/tree/a%20b"
    assert urls.blob_url("foo", "dir/#1?é.txt") == "/foo/blob/dir/%231%3F%C3%A9.txt"
    assert urls.raw_url("foo", "100%.txt") == "/foo/raw/100%25.txt"
    assert urls.archive_url("foo", "tar.gz") == "/foo/archive/foo.tar.gz"


def make_linker():
    return Linker(
        "foo",
        files={"README.md", "docs/x.md", "docs/img.png", "y.txt"},
        dirs={"", "docs", "docs/sub"},
    )


def test_linker_resolves_relative_links():
    link = make_linker()
    assert link.resolve("", "docs/x.md") == "/foo/blob/docs/x.md"
    assert link.resolve("docs", "../y.txt") == "/foo/blob/y.txt"
    assert link.resolve("docs", "sub/") == "/foo/tree/docs/sub"
    assert link.resolve("docs", "sub") == "/foo/tree/docs/sub"
    assert link.resolve("docs", "..") == "/foo"
    assert link.resolve("docs", "img.png", raw=True) == "/foo/raw/docs/img.png"
    assert link.resolve("", "docs/x.md#part") == "/foo/blob/docs/x.md#part"


def test_linker_leaves_other_links_alone():
    link = make_linker()
    for href in [
        "https://example.com/x",
        "mailto:a@b",
        "#anchor",
        "/abs/path",
        "../../outside",
        "",
    ]:
        assert link.resolve("docs", href) == href


def test_markdown_escapes_raw_html():
    html = render_markdown(
        "hi <script>alert(1)</script>\n\n<b>x</b>\n", "", make_linker()
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>" not in html


def test_markdown_rewrites_links_and_images():
    html = render_markdown(
        "[x](x.md) ![i](img.png) [ext](https://e.com)\n", "docs", make_linker()
    )
    assert 'href="/foo/blob/docs/x.md"' in html
    assert 'src="/foo/raw/docs/img.png"' in html
    assert 'href="https://e.com"' in html


def test_markdown_drops_javascript_links():
    html = render_markdown("[x](javascript:alert(1))\n", "", make_linker())
    assert 'href="javascript' not in html


def test_markdown_tables():
    html = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n", "", make_linker())
    assert "<table>" in html


def test_highlight():
    html = highlight_file("x.py", "def f():\n    return 1\n")
    assert 'class="hl' in html and "def" in html
    assert highlight_file("unknown.zzz", "<b>").count("&lt;b&gt;") == 1
    assert ".hl" in pygments_css()
