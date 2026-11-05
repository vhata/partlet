"""Theme publication preserves Git state and every advertised stylesheet."""

import base64
import json
import re
from dataclasses import replace

import pytest
from helpers import export_tip

from partlet import publish
from partlet.manifest import ThemeConfig, parse_manifest
from partlet.publish import publish_all, unpublish_project, write_site_index
from partlet.site.render import site_stylesheet
from partlet.site.themes import ThemeError, resolve_theme
from partlet.store import LocalStore, StoreError


def manifest(approved, theme="classic", mode="auto"):
    return parse_manifest(f"""[site]
source = "s"
base_url = "https://partlet.example"
[site.theme]
name = "{theme}"
mode = "{mode}"
[projects.foo]
path = "foo"
approved = "{approved}"
""")


def run(mono, tmp_path, store, config, **kwargs):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    return publish_all(mono.path, config, store, work, **kwargs)


def current(store):
    return json.loads(store.get("s/p/foo/current"))


def resource_key(theme, name="style.css"):
    return f"s/static/themes/{theme.digest}/{name}"


def stylesheet(page):
    return re.search(rb'href="(/_partlet/themes/[0-9a-f]{64}/style\.css)"', page)[1]


@pytest.fixture
def prepared(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.write("foo/docs/README.md", "# Documentation\n")
    mono.commit("first source")
    approved = export_tip(mono, tmp_path)
    return manifest(approved), LocalStore(tmp_path / "out")


def test_theme_change_rerenders_without_changing_git_or_archives(
    mono, tmp_path, prepared
):
    config, store = prepared
    assert run(mono, tmp_path, store, config)[0].status == "published"
    before = current(store)
    git_before = {key: store.get(key) for key in store.list("s/p/foo/git/")}
    archives_before = {key: store.get(key) for key in store.list("s/p/foo/archive/")}
    old_theme = resolve_theme(config.site.theme)
    old_css = store.get(resource_key(old_theme))
    old_page = store.get(f"s/p/foo/site/{before['build']}/index.html")

    changed = manifest(before["tip"], "paper", "dark")
    result = run(mono, tmp_path, store, changed)[0]
    after = current(store)
    assert (result.status, result.reason) == ("published", "re-rendered")
    assert after["tip"] == before["tip"]
    assert after["build"] != before["build"]
    assert after["previous"]["build"] == before["build"]
    assert {key: store.get(key) for key in store.list("s/p/foo/git/")} == git_before
    assert {
        key: store.get(key) for key in store.list("s/p/foo/archive/")
    } == archives_before
    assert store.get(resource_key(old_theme)) == old_css
    assert store.get(f"s/p/foo/site/{before['build']}/index.html") == old_page
    theme = resolve_theme(changed.site.theme)
    expected_url = theme.stylesheet_url.encode()
    for key in store.list(f"s/p/foo/site/{after['build']}/"):
        if "/raw/" not in key:
            assert stylesheet(store.get(key)) == expected_url
    assert stylesheet(store.get("s/index.html")) == expected_url
    assert store.get("s/static/style.css") == site_stylesheet()
    assert run(mono, tmp_path, store, changed)[0].status == "unchanged"


def test_mode_change_changes_build_identity(mono, tmp_path, prepared):
    config, store = prepared
    run(mono, tmp_path, store, config)
    old = current(store)
    changed = manifest(old["tip"], "classic", "light")
    assert run(mono, tmp_path, store, changed)[0].status == "published"
    assert current(store)["build"] != old["build"]


def test_resources_exist_before_any_referencing_page_or_pointer(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    theme = resolve_theme(config.site.theme)
    original_put = store.put
    seen = []

    def record(key, data, content_type=None):
        if "/site/" in key or key in (
            "s/p/foo/current",
            "s/index.html",
            "s/site-theme.json",
        ):
            for resource in theme.resources:
                assert store.get(resource_key(theme, resource.path)) == resource.data
        seen.append(key)
        original_put(key, data, content_type)

    monkeypatch.setattr(store, "put", record)
    assert run(mono, tmp_path, store, config)[0].status == "published"
    assert resource_key(theme) in seen
    assert "s/p/foo/current" in seen
    assert "s/index.html" in seen


def test_failure_uploading_theme_never_advertises_it(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    run(mono, tmp_path, store, config)
    old_current = store.get("s/p/foo/current")
    old_index = store.get("s/index.html")
    changed = manifest(config.projects["foo"].approved, "terminal")
    theme = resolve_theme(changed.site.theme)
    original_put = store.put

    def fail_resource(key, data, content_type=None):
        if key == resource_key(theme):
            raise StoreError("interrupted stylesheet upload")
        original_put(key, data, content_type)

    with monkeypatch.context() as mp:
        mp.setattr(store, "put", fail_resource)
        with pytest.raises(StoreError, match="interrupted stylesheet"):
            run(mono, tmp_path, store, changed)
    assert store.get("s/p/foo/current") == old_current
    assert store.get("s/index.html") == old_index
    assert run(mono, tmp_path, store, changed)[0].status == "published"
    assert stylesheet(store.get("s/index.html")) == theme.stylesheet_url.encode()


def test_theme_resources_retained_for_skipped_and_failed_projects(
    mono, tmp_path, prepared
):
    config, store = prepared
    run(mono, tmp_path, store, config)
    old_current = store.get("s/p/foo/current")
    old_theme = resolve_theme(config.site.theme)
    new_theme = resolve_theme(ThemeConfig(name="paper"))
    skipped = replace(
        config,
        site=replace(config.site, theme=ThemeConfig(name="paper")),
        projects={"foo": replace(config.projects["foo"], approved=None)},
    )
    assert run(mono, tmp_path, store, skipped)[0].status == "skipped"
    assert store.get("s/p/foo/current") == old_current
    assert store.get(resource_key(old_theme)) is not None
    assert store.get(resource_key(new_theme)) is not None

    failed = replace(
        skipped,
        projects={"foo": replace(config.projects["foo"], path="missing")},
    )
    assert run(mono, tmp_path, store, failed)[0].status == "failed"
    assert store.get("s/p/foo/current") == old_current
    assert store.get(resource_key(old_theme)) is not None
    assert stylesheet(store.get("s/index.html")) == new_theme.stylesheet_url.encode()


def test_invalid_theme_fails_before_any_store_write(mono, tmp_path, prepared):
    config, store = prepared
    invalid = replace(
        config,
        site=replace(config.site, theme=ThemeConfig(name=None, path="themes/missing")),
    )
    with pytest.raises(ThemeError):
        run(mono, tmp_path, store, invalid)
    assert store.list("") == []


def test_publish_all_resolves_once_and_passes_one_snapshot(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    real_resolve = publish.resolve_theme
    themes = []

    def resolve(*args, **kwargs):
        theme = real_resolve(*args, **kwargs)
        themes.append(theme)
        return theme

    real_project = publish.publish_project
    received = []

    def project(*args, **kwargs):
        received.append(kwargs["theme"])
        return real_project(*args, **kwargs)

    monkeypatch.setattr(publish, "resolve_theme", resolve)
    monkeypatch.setattr(publish, "publish_project", project)
    assert run(mono, tmp_path, store, config)[0].status == "published"
    assert len(themes) == 1
    assert received == themes
    assert stylesheet(store.get("s/index.html")) == themes[0].stylesheet_url.encode()


def test_unpublish_preserves_stored_theme_without_loading_source(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    themed = manifest(config.projects["foo"].approved, "paper", "dark")
    run(mono, tmp_path, store, themed)
    before = json.loads(store.get("s/site-theme.json"))
    theme_url = stylesheet(store.get("s/index.html"))

    def no_source(*args, **kwargs):
        raise AssertionError("unpublish must not resolve local theme files")

    monkeypatch.setattr(publish, "resolve_theme", no_source)
    # Even if the new local config points to a missing third-party folder,
    # removal uses durable presentation metadata from the published site.
    site = replace(themed.site, theme=ThemeConfig(name=None, path="missing"))
    unpublish_project(store, site, "foo")
    assert store.list("s/p/foo/") == []
    assert stylesheet(store.get("s/index.html")) == theme_url
    assert json.loads(store.get("s/site-theme.json")) == before


@pytest.mark.parametrize(
    "record",
    [
        b"{",
        b"null",
        b"[]",
        b'{"name":"paper","mode":"dark","digest":"../private"}',
        json.dumps({"name": "paper", "mode": "dark", "digest": "A" * 64}).encode(),
        json.dumps({"name": "paper", "mode": "other", "digest": "a" * 64}).encode(),
        json.dumps({"name": "../private", "mode": "auto", "digest": "a" * 64}).encode(),
        json.dumps({"name": ["paper"], "mode": "auto", "digest": "a" * 64}).encode(),
        b"\xff",
    ],
)
def test_corrupt_presentation_cannot_remove_live_state(
    mono, tmp_path, prepared, record
):
    config, store = prepared
    run(mono, tmp_path, store, config)
    store.put("s/site-theme.json", record)
    before = {key: store.get(key) for key in store.list("")}
    with pytest.raises(StoreError, match="invalid stored site theme"):
        unpublish_project(store, config.site, "foo")
    assert {key: store.get(key) for key in store.list("")} == before


def test_missing_metadata_keeps_legacy_index_and_css(tmp_path):
    store = LocalStore(tmp_path / "out")
    config = manifest("a" * 40, "paper")
    write_site_index(store, config.site)
    assert b'href="/_partlet/style.css"' in store.get("s/index.html")
    assert store.get("s/static/style.css") == site_stylesheet()
    assert store.get("s/site-theme.json") is None


def test_same_build_repairs_missing_theme_resources(mono, tmp_path, prepared):
    config, store = prepared
    run(mono, tmp_path, store, config)
    theme = resolve_theme(config.site.theme)
    store.delete(resource_key(theme))
    assert run(mono, tmp_path, store, config)[0].status == "unchanged"
    assert store.get(resource_key(theme)) is not None


def test_metadata_failure_cannot_advertise_new_index(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    run(mono, tmp_path, store, config)
    old_index = store.get("s/index.html")
    old_record = store.get("s/site-theme.json")
    theme = resolve_theme(ThemeConfig(name="paper"))
    original_put = store.put

    def fail_metadata(key, data, content_type=None):
        if key == "s/site-theme.json":
            raise StoreError("metadata interrupted")
        original_put(key, data, content_type)

    with monkeypatch.context() as mp:
        mp.setattr(store, "put", fail_metadata)
        with pytest.raises(StoreError, match="metadata interrupted"):
            write_site_index(store, config.site, theme)
    assert store.get("s/index.html") == old_index
    assert store.get("s/site-theme.json") == old_record
    assert store.get(resource_key(theme)) is not None
    write_site_index(store, config.site, theme)
    assert stylesheet(store.get("s/index.html")) == theme.stylesheet_url.encode()


def test_unpublish_completes_presentation_after_interrupted_index_write(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    run(mono, tmp_path, store, config)
    old_index = store.get("s/index.html")
    theme = resolve_theme(ThemeConfig(name="paper"))
    original_put = store.put

    def fail_index(key, data, content_type=None):
        if key == "s/index.html":
            raise StoreError("index interrupted")
        original_put(key, data, content_type)

    with monkeypatch.context() as mp:
        mp.setattr(store, "put", fail_index)
        with pytest.raises(StoreError, match="index interrupted"):
            write_site_index(store, config.site, theme)
    assert store.get("s/index.html") == old_index
    assert json.loads(store.get("s/site-theme.json"))["digest"] == theme.digest
    unpublish_project(store, config.site, "foo")
    assert stylesheet(store.get("s/index.html")) == theme.stylesheet_url.encode()


def custom_pack(mono):
    mono.write(
        "themes/custom/theme.toml",
        'id = "custom"\nname = "Custom theme"\nversion = "1.0"\n'
        'format_version = 1\nmodes = ["auto", "light", "dark"]\n'
        'license = "MIT"\nassets = ["assets/logo.png"]\n',
    )
    mono.write(
        "themes/custom/style.css",
        ':root { --link: #123456; }\nheader.top { background-image: url("assets/logo.png"); }\n',
    )
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO2cAAAAASUVORK5CYII="
    )
    mono.write("themes/custom/assets/logo.png", image)
    mono.write("themes/custom/notes.txt", "PRIVATE_THEME_NOTES\n")
    mono.write("themes/custom/LICENSE", "Example license provenance\n")
    mono.commit("vendored theme")
    return ThemeConfig(name=None, path="themes/custom")


def test_vendored_assets_are_explicit_public_inputs(mono, tmp_path, prepared):
    config, store = prepared
    selected = custom_pack(mono)
    themed = replace(config, site=replace(config.site, theme=selected))
    theme = resolve_theme(selected, mono.path)
    assert run(mono, tmp_path, store, themed)[0].status == "published"
    assert set(store.list(f"s/static/themes/{theme.digest}/")) == {
        resource_key(theme, "style.css"),
        resource_key(theme, "assets/logo.png"),
    }
    for resource in theme.resources:
        assert store.get(resource_key(theme, resource.path)) == resource.data
    assert all(b"PRIVATE_THEME_NOTES" not in store.get(key) for key in store.list(""))
    old = current(store)
    git_before = {key: store.get(key) for key in store.list("s/p/foo/git/")}
    image_path = mono.path / "themes/custom/assets/logo.png"
    image_path.write_bytes(image_path.read_bytes() + b"theme asset changed")
    mono.commit("change theme asset only")
    changed = resolve_theme(selected, mono.path)
    assert changed.digest != theme.digest
    assert run(mono, tmp_path, store, themed)[0].status == "published"
    assert current(store)["tip"] == old["tip"]
    assert current(store)["build"] != old["build"]
    assert {key: store.get(key) for key in store.list("s/p/foo/git/")} == git_before
    assert store.get(resource_key(theme, "assets/logo.png")) is not None


def test_commit_changing_during_upload_cannot_mix_theme_versions(
    mono, tmp_path, prepared, monkeypatch
):
    config, store = prepared
    selected = custom_pack(mono)
    themed = replace(config, site=replace(config.site, theme=selected))
    original = resolve_theme(selected, mono.path)
    original_put = store.put
    mutated = False

    def change_commit_on_upload(key, data, content_type=None):
        nonlocal mutated
        if not mutated and key.startswith("s/static/themes/"):
            mutated = True
            path = mono.path / "themes/custom/style.css"
            path.write_text(path.read_text().replace("#123456", "#654321"))
            mono.commit("new theme while publisher is running")
        original_put(key, data, content_type)

    monkeypatch.setattr(store, "put", change_commit_on_upload)
    assert run(mono, tmp_path, store, themed)[0].status == "published"
    assert mutated
    assert json.loads(store.get("s/site-theme.json"))["digest"] == original.digest
    assert stylesheet(store.get("s/index.html")) == original.stylesheet_url.encode()
    for resource in original.resources:
        assert store.get(resource_key(original, resource.path)) == resource.data
    changed = resolve_theme(selected, mono.path)
    assert changed.digest != original.digest
    assert store.get(resource_key(changed)) is None
    assert run(mono, tmp_path, store, themed)[0].status == "published"
    assert json.loads(store.get("s/site-theme.json"))["digest"] == changed.digest
