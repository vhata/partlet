"""Theme discovery and validation use local committed inputs only."""

import json
import os
from dataclasses import replace

import pytest
from helpers import export_tip

from partlet import cli
from partlet.cli import main
from partlet.manifest import ThemeConfig, load_manifest
from partlet.site.themes import resolve_theme
from partlet.store import LocalStore, R2Store


def write_theme(mono, directory="themes/custom"):
    mono.write(
        f"{directory}/theme.toml",
        'id = "custom"\nname = "Custom theme"\nversion = "1.0"\n'
        'format_version = 1\nmodes = ["auto", "light", "dark"]\n'
        'license = "MIT"\nassets = []\n',
    )
    mono.write(f"{directory}/style.css", ":root { --link: #123456; }\n")
    mono.write(f"{directory}/LICENSE", "Example license provenance\n")


@pytest.fixture
def configured(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("source")
    approved = export_tip(mono, tmp_path)
    write_theme(mono)
    mono.write(
        "partlet.toml",
        '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n'
        '[site.theme]\npath = "themes/custom"\nmode = "dark"\n'
        f'[projects.foo]\npath = "foo"\napproved = "{approved}"\n',
    )
    mono.commit("theme and approval")
    return mono.path / "partlet.toml"


def test_list_needs_no_manifest_tools_or_credentials(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("theme list must not inspect a repo or toolchain")

    monkeypatch.setattr(cli, "load_manifest", forbidden)
    monkeypatch.setattr(cli, "check_tools", forbidden)
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "local-only-secret")
    assert main(["theme", "list"]) == 0
    output = capsys.readouterr().out
    for word in ("classic", "paper", "terminal", "auto", "light", "dark"):
        assert word in output
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in os.environ


def test_check_reports_selected_theme_and_committed_inputs(
    mono, configured, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError("theme check must not run publisher tool checks")

    monkeypatch.setattr(cli, "check_tools", forbidden)
    monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", "local-only-key")
    assert main(["theme", "check", "--repo", str(mono.path)]) == 0
    output = capsys.readouterr().out
    assert "Theme: custom; mode: dark" in output
    assert "Fingerprint:" in output
    assert "refs/heads/main" in output
    assert "local file edits are not included" in output
    assert "PARTLET_R2_ACCESS_KEY_ID" not in os.environ


def test_local_build_and_check_ignore_uncommitted_theme_edits(
    mono, tmp_path, configured, capsys
):
    parsed = load_manifest(configured)
    original = resolve_theme(parsed.site.theme, mono.path)
    mono.write("themes/custom/style.css", ":root { --link: #654321; }\n")
    assert main(["theme", "check", "--repo", str(mono.path)]) == 0
    assert original.digest in capsys.readouterr().out
    out = tmp_path / "out"
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    store = LocalStore(out)
    assert json.loads(store.get("s/site-theme.json"))["digest"] == original.digest
    assert b"#123456" in store.get(f"s/static/themes/{original.digest}/style.css")
    assert b"#654321" not in store.get(f"s/static/themes/{original.digest}/style.css")


def test_production_rejects_dirty_theme_before_lock_or_uploads(
    mono, tmp_path, configured, r2_env, capsys
):
    mono.write("themes/custom/style.css", ":root { --link: #654321; }\n")
    assert main(["publish", "--repo", str(mono.path)]) == 2
    assert "differs" in capsys.readouterr().err
    assert R2Store(r2_env).list("s/") == []


def test_committed_input_mode_rechecks_theme_before_local_action_writes(
    mono, tmp_path, configured, capsys
):
    mono.write("themes/custom/style.css", ":root { --link: #654321; }\n")
    out = tmp_path / "out"
    assert (
        main(
            ["build", "--repo", str(mono.path), "--out", str(out)],
            require_committed=True,
        )
        == 2
    )
    assert "differs" in capsys.readouterr().err
    assert not out.exists()


def test_committed_input_mode_rechecks_manifest_snapshot(
    mono, tmp_path, configured, monkeypatch, capsys
):
    original = configured.read_text()
    configured.write_text(original + "# transient edit\n")
    real_load = cli.load_manifest

    def read_then_restore(path):
        manifest = real_load(path)
        # This changes the parsed configuration while the manifest on disk is
        # restored to its committed version before check_checkout rereads it.
        manifest = replace(
            manifest,
            site=replace(manifest.site, theme=ThemeConfig(name="paper")),
        )
        path.write_text(original)
        return manifest

    monkeypatch.setattr(cli, "load_manifest", read_then_restore)
    out = tmp_path / "out"
    assert (
        main(
            ["build", "--repo", str(mono.path), "--out", str(out)],
            require_committed=True,
        )
        == 2
    )
    assert "manifest changed while reading" in capsys.readouterr().err
    assert not out.exists()


def test_nested_manifest_resolves_theme_relative_to_manifest_directory(
    mono, tmp_path, configured
):
    text = configured.read_text()
    mono.write("config/public.toml", text)
    write_theme(mono, "config/themes/custom")
    mono.write("config/themes/custom/style.css", ":root { --link: #789abc; }\n")
    mono.commit("nested manifest with its own theme")
    manifest_path = mono.path / "config/public.toml"
    selected = load_manifest(manifest_path)
    expected = resolve_theme(
        selected.site.theme, mono.path, manifest_path=manifest_path
    )
    out = tmp_path / "out"
    assert (
        main(
            [
                "build",
                "--repo",
                str(mono.path),
                "--manifest",
                str(manifest_path),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert (
        json.loads(LocalStore(out).get("s/site-theme.json"))["digest"]
        == expected.digest
    )


@pytest.mark.parametrize("command", ["build", "check"])
def test_invalid_custom_theme_reports_error_without_creating_output(
    mono, tmp_path, configured, capsys, command
):
    mono.write("themes/custom/theme.toml", "format_version = 999\n")
    mono.commit("incompatible theme")
    out = tmp_path / "out"
    args = (
        ["build", "--repo", str(mono.path), "--out", str(out)]
        if command == "build"
        else ["theme", "check", "--repo", str(mono.path)]
    )
    assert main(args) == 2
    assert "theme.toml" in capsys.readouterr().err
    assert not out.exists()
