"""Homepage input privacy, source-free recovery and presentation identity."""

import json
from dataclasses import replace

import pytest
from helpers import export_tip

from partlet.manifest import ManifestError, Site, parse_manifest
from partlet.publish import publish_all, unpublish_project
from partlet.site.homepage import HomepageError, load_homepage, stored_homepage
from partlet.site.render import render_site_index
from partlet.store import LocalStore, StoreError


def test_explicit_committed_input_and_no_autodiscovery(mono):
    mono.write("README.md", "# Private root")
    mono.write(
        "public/home.md",
        "# Public\n\n[Project](/foo/) ![Image](https://example.test/i.png)",
    )
    mono.commit("inputs")
    site = Site("s", "main", "https://example.test")
    assert load_homepage(mono.path, site) is None
    site = replace(site, readme="public/home.md")
    expected = load_homepage(mono.path, site)
    mono.write("public/home.md", "# Dirty")
    assert load_homepage(mono.path, site) == expected
    with pytest.raises(HomepageError, match="uncommitted"):
        load_homepage(mono.path, site, require_clean=True)
    assert "Private" not in expected


@pytest.mark.parametrize(
    "path",
    [
        "/a.md",
        "../a.md",
        "a/../b.md",
        "a//b.md",
        "./a.md",
        "C:/a.md",
        "a.txt",
        "",
        "a\\b.md",
    ],
)
def test_invalid_manifest_path(path):
    with pytest.raises(ManifestError):
        parse_manifest(
            '[site]\nsource="s"\nbase_url="https://x"\nreadme=' + json.dumps(path)
        )


@pytest.mark.parametrize("path", ["missing.md", "link.md", "linked/home.md"])
def test_missing_and_symlink_inputs(mono, path):
    mono.write("public/home.md", "# public")
    mono.symlink("link.md", "public/home.md")
    mono.symlink("linked", "public")
    mono.commit("inputs")
    with pytest.raises(HomepageError, match="committed regular"):
        load_homepage(mono.path, Site("s", "main", "https://x", readme=path))


@pytest.mark.parametrize(
    "link",
    ["private.txt", "../secret.md", "images/private.png", "//external.test/image"],
)
def test_ambiguous_links_are_actionable(mono, link):
    mono.write("home.md", f"[link]({link})")
    mono.commit("input")
    with pytest.raises(HomepageError, match="root-relative"):
        load_homepage(mono.path, Site("s", "main", "https://x", readme="home.md"))


def test_inert_markdown_and_durable_validation(mono):
    mono.write(
        "home.md",
        "<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n[ok](#top)\n\n| A |\n| :- |\n| B |",
    )
    mono.commit("input")
    site = Site("s", "main", "https://x")
    intro = load_homepage(mono.path, replace(site, readme="home.md"))
    record = {"version": 1, "name": "<name>", "tagline": "<tag>", "intro_html": intro}
    identity, restored = stored_homepage(json.dumps(record).encode(), site)
    page = render_site_index(site.base_url, [], identity=identity, intro_html=restored)
    assert b"<script>" not in page and b'href="javascript:' not in page
    assert b"&lt;name&gt;" in page and b"&lt;tag&gt;" in page
    assert restored == intro


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {},
        {"version": True, "name": "x", "tagline": "", "intro_html": None},
        {"version": 1, "name": [], "tagline": "", "intro_html": None},
        {
            "version": 1,
            "name": "x",
            "tagline": "",
            "intro_html": '<img src="javascript:alert(1)">',
        },
        {
            "version": 1,
            "name": "x",
            "tagline": "",
            "intro_html": '<p onclick="x">x</p>',
        },
    ],
)
def test_bad_metadata_blocks_removal(tmp_path, record):
    store = LocalStore(tmp_path / "out")
    store.put("s/site-identity.json", json.dumps(record).encode())
    store.put("s/p/foo/current", b"{}")
    before = {k: store.get(k) for k in store.list("")}
    with pytest.raises(StoreError, match="stored site identity"):
        unpublish_project(store, Site("s", "main", "https://x"), "foo")
    assert before == {k: store.get(k) for k in store.list("")}


def test_readme_only_change_and_source_free_removal(mono, tmp_path):
    mono.write("foo/a", "exported")
    mono.write("home.md", "# First")
    mono.commit("input")
    tip = export_tip(mono, tmp_path)
    config = parse_manifest(
        f'[site]\nsource="s"\nbase_url="https://x"\nname="Public"\ntagline="Footer"\nreadme="home.md"\n[projects.foo]\npath="foo"\napproved="{tip}"'
    )
    store = LocalStore(tmp_path / "out")
    assert (
        publish_all(mono.path, config, store, tmp_path / "w1")[0].status == "published"
    )
    before = store.get("s/p/foo/current")
    mono.write("home.md", "# Second")
    mono.commit("homepage only")
    assert (
        publish_all(mono.path, config, store, tmp_path / "w2")[0].status == "unchanged"
    )
    assert store.get("s/p/foo/current") == before
    assert b"Second" in store.get("s/index.html")
    record = json.loads(store.get("s/site-identity.json"))
    assert set(record) == {"version", "name", "tagline", "intro_html"}
    mono.rm("home.md")
    mono.commit("remove source")
    unpublish_project(store, replace(config.site, name="Wrong", tagline="Wrong"), "foo")
    page = store.get("s/index.html")
    assert b"Second" in page and b"Public" in page and b"Footer" in page
    assert b"Wrong" not in page


def test_identity_change_and_partial_publication(mono, tmp_path, monkeypatch):
    mono.write("foo/a", "exported")
    mono.commit("input")
    tip = export_tip(mono, tmp_path)
    config = parse_manifest(
        f'[site]\nsource="s"\nbase_url="https://x"\n[projects.foo]\npath="foo"\napproved="{tip}"'
    )
    store = LocalStore(tmp_path / "out")
    publish_all(mono.path, config, store, tmp_path / "w1")
    before = json.loads(store.get("s/p/foo/current"))
    changed = replace(config, site=replace(config.site, name="New", tagline="Footer"))
    result = publish_all(mono.path, changed, store, tmp_path / "w2")[0]
    after = json.loads(store.get("s/p/foo/current"))
    assert result.status == "published" and after["tip"] == before["tip"]
    assert after["build"] != before["build"]
    failed = replace(
        changed,
        site=replace(changed.site, name="Latest"),
        projects={"foo": replace(changed.projects["foo"], path="missing")},
    )
    assert publish_all(mono.path, failed, store, tmp_path / "w3")[0].status == "failed"
    assert json.loads(store.get("s/p/foo/current")) == after
    assert b"Latest" in store.get("s/index.html")
    assert b"New" in store.get(f"s/p/foo/site/{after['build']}/index.html")
    original = store.put

    def fail_index(key, data, content_type=None):
        if key == "s/index.html":
            raise StoreError("interrupted")
        original(key, data, content_type)

    with monkeypatch.context() as mp:
        mp.setattr(store, "put", fail_index)
        with pytest.raises(StoreError, match="interrupted"):
            publish_all(mono.path, changed, store, tmp_path / "w4")
    unpublish_project(store, config.site, "foo")
    assert b"New" in store.get("s/index.html")


@pytest.mark.parametrize("field", ["name", "tagline", "readme"])
def test_invalid_identity_types(field):
    with pytest.raises(ManifestError, match="must be a string"):
        parse_manifest(f'[site]\nsource="s"\nbase_url="https://x"\n{field}=42')


def test_preview_shares_homepage_renderer_and_never_copies_assets(mono, tmp_path):
    from partlet.preview import build_preview
    from partlet.site.themes import resolve_theme

    mono.write("foo/a", "public")
    mono.write("home.md", "# Homepage\n\n![public URL](/images/secret.png)")
    mono.write("images/secret.png", "PRIVATE_CONTENT")
    mono.commit("inputs")
    config = parse_manifest(
        '[site]\nsource="s"\nbase_url="https://example.test"\nreadme="home.md"\n[projects.foo]\npath="foo"'
    )
    (tmp_path / "preview").mkdir()
    root = build_preview(mono.path, config, tmp_path / "preview", 8899, resolve_theme())
    store = LocalStore(root)
    assert b"<h1>Homepage</h1>" in store.get("s/index.html")
    assert b"example.test" in store.get("s/index.html")
    assert not any(b"PRIVATE_CONTENT" in store.get(key) for key in store.list(""))
    assert not any("images/secret" in key for key in store.list(""))


@pytest.mark.parametrize("field", ["name", "tagline", "intro_html"])
def test_invalid_unicode_metadata_cannot_remove_live_state(tmp_path, field):
    record = {"version": 1, "name": "x", "tagline": "", "intro_html": None}
    record[field] = "\ud800"
    test_bad_metadata_blocks_removal(tmp_path, record)


@pytest.mark.parametrize("git_repository", [True, False])
def test_build_reports_homepage_source_errors(mono, tmp_path, capsys, git_repository):
    from partlet.cli import main

    manifest = (
        '[site]\nsource="s"\nbase_url="https://example.test"\n'
        'branch="absent"\nreadme="home.md"\n'
    )
    if git_repository:
        mono.write("home.md", "# Public homepage")
        mono.write("partlet.toml", manifest)
        mono.commit("homepage configuration")
        repo = mono.path
    else:
        repo = tmp_path / "not-a-repository"
        repo.mkdir()
        (repo / "partlet.toml").write_text(manifest)
    out = tmp_path / "output"
    assert main(["build", "--repo", str(repo), "--out", str(out)]) == 2
    error = capsys.readouterr().err
    assert "site.readme" in error and "local branch 'absent'" in error
    assert "--repo" in error and "fetch or create" in error
    assert "Traceback" not in error
    assert not out.exists()
