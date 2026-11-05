"""Installed-tool bootstrap, failure recovery, and checkout-independent assets."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from partlet import runtime
from partlet.scan import GITLEAKS_VERSION, find_gitleaks

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTLET_DATA_DIR", str(tmp_path / "Partlet data"))
    return tmp_path / "Partlet data"


def executable(path, body="exit 0"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)


def test_data_root_override_and_platform_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTLET_DATA_DIR", str(tmp_path / "override"))
    assert runtime.data_root() == tmp_path / "override"
    monkeypatch.delenv("PARTLET_DATA_DIR")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert runtime.data_root() == tmp_path / "xdg" / "partlet"
    monkeypatch.delenv("XDG_DATA_HOME")
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    assert runtime.data_root() == Path.home() / "Library/Application Support/partlet"
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    assert runtime.data_root() == Path.home() / ".local/share/partlet"


def test_worker_lookup_never_downloads(isolated, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("lookup attempted to install tools")

    monkeypatch.setattr(runtime.subprocess, "run", unexpected)
    with pytest.raises(runtime.SetupError, match="partlet setup --worker"):
        runtime.worker_root()
    assert not isolated.exists()


def test_worker_cache_changes_with_assets(isolated, tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    for source in runtime._worker_files():
        destination = (
            assets / "worker" / source.relative_to(runtime.asset_root() / "worker")
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    monkeypatch.setattr(runtime, "asset_root", lambda: assets)
    before = runtime._worker_destination()
    (assets / "worker/src/route.ts").write_text("// new source, same Partlet version\n")
    assert runtime._worker_destination() != before
    before = runtime._worker_destination()
    (assets / "worker/.node-version").write_text("26.1.0\n")
    assert runtime._worker_destination() != before


def test_setup_worker_failure_has_no_ready_runtime_and_retries(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(runtime, "_install_scanner", lambda *args: None)
    monkeypatch.setattr(runtime, "_node_tools", lambda *args: "npm")

    def fail(command, **kwargs):
        calls.append(kwargs["cwd"])
        (kwargs["cwd"] / "node_modules").mkdir()
        raise runtime.SetupError("simulated npm failure")

    monkeypatch.setattr(runtime, "_run", fail)
    with pytest.raises(runtime.SetupError, match="simulated npm failure"):
        runtime.setup(worker=True)
    with pytest.raises(runtime.SetupError, match="partlet setup --worker"):
        runtime.worker_root()
    assert list((isolated / "workers").iterdir()) == []

    def succeed(command, **kwargs):
        assert command[1:] == [
            "ci",
            "--include=dev",
            "--no-audit",
            "--no-fund",
            "--registry=https://registry.npmjs.org",
        ]
        calls.append(kwargs["cwd"])
        executable(kwargs["cwd"] / "node_modules/.bin/wrangler")

    monkeypatch.setattr(runtime, "_run", succeed)
    runtime.setup(worker=True)
    prepared = runtime.worker_root()
    assert (prepared / "src/index.ts").read_bytes() == (
        ROOT / "worker/src/index.ts"
    ).read_bytes()
    assert (prepared / "tools/seed-r2.mjs").is_file()
    assert (prepared / ".complete").is_file()
    runtime.setup(worker=True)
    assert len(calls) == 2  # completed setup is reusable


def test_setup_rejects_success_without_wrangler(isolated, monkeypatch):
    monkeypatch.setattr(runtime, "_install_scanner", lambda *args: None)
    monkeypatch.setattr(runtime, "_node_tools", lambda *args: "npm")
    monkeypatch.setattr(runtime, "_run", lambda *args, **kwargs: None)
    with pytest.raises(runtime.SetupError, match="did not install Wrangler"):
        runtime.setup(worker=True)
    with pytest.raises(runtime.SetupError):
        runtime.worker_root()


def test_setup_environment_drops_credentials_and_npm_overrides(isolated, monkeypatch):
    for key in (
        "PARTLET_R2_SECRET_ACCESS_KEY",
        "CLOUDFLARE_API_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "npm_config_ignore_scripts",
        "NPM_CONFIG_REGISTRY",
        "NODE_OPTIONS",
        "BASH_ENV",
        "GIT_DIR",
        "GIT_CONFIG_KEY_0",
    ):
        monkeypatch.setenv(key, "should-not-reach-installers")
    env = runtime._setup_env()
    assert "should-not-reach-installers" not in env.values()
    assert env["npm_config_userconfig"] == os.devnull
    assert env["npm_config_globalconfig"] == str(isolated / "npm-globalrc")
    assert env["npm_config_cache"] == str(isolated / "npm-cache")


def test_setup_environment_works_with_real_npm(isolated):
    isolated.mkdir()
    npm = shutil.which("npm")
    assert npm is not None, "npm is a required Worker test prerequisite"
    result = subprocess.run(
        [npm, "--version"],
        cwd=isolated,
        env=runtime._setup_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "node,npm,error",
    [
        ("v22.1.0", "11.19.0", "Node"),
        ("v24.22.0", "11.18.0", "npm >=11.19"),
        ("invalid", "11.19.0", "determine node"),
    ],
)
def test_setup_checks_supported_node_and_npm(isolated, monkeypatch, node, npm, error):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: name)

    def version(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 0, node if command[0] == "node" else npm, ""
        )

    monkeypatch.setattr(runtime.subprocess, "run", version)
    with pytest.raises(runtime.SetupError, match=error):
        runtime._node_tools(runtime._setup_env(), isolated)


def test_setup_missing_node_is_actionable(isolated, monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: None)
    with pytest.raises(runtime.SetupError, match="install Node.*npm >=11.19"):
        runtime._node_tools(runtime._setup_env(), isolated)


def test_scanner_install_is_verified_then_atomically_published(isolated, monkeypatch):
    calls = []
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "must-not-reach-version-probe")

    def install(command, **kwargs):
        calls.append(command)
        executable(
            Path(command[-1]) / "gitleaks",
            'test -z "$PARTLET_R2_SECRET_ACCESS_KEY" || exit 99\n'
            f"echo {GITLEAKS_VERSION}",
        )

    monkeypatch.setattr(runtime, "_run", install)
    runtime.setup()
    assert runtime.managed_gitleaks().is_file()
    assert find_gitleaks() == str(runtime.managed_gitleaks())
    runtime.setup()
    assert len(calls) == 1
    executable(runtime.managed_gitleaks(), "echo wrong-version")
    runtime.setup()
    assert len(calls) == 2


def test_invalid_scanner_download_is_not_published(isolated, monkeypatch):
    def install(command, **kwargs):
        executable(Path(command[-1]) / "gitleaks", "echo wrong-version")

    monkeypatch.setattr(runtime, "_run", install)
    with pytest.raises(runtime.SetupError, match="needs gitleaks"):
        runtime.setup()
    assert not runtime.managed_gitleaks().exists()


@pytest.mark.parametrize(
    "arguments,setup_command",
    [([], "setup --worker"), (["--publisher-only"], "setup")],
)
def test_installer_uses_exact_uv_installed_command(tmp_path, arguments, setup_command):
    commands = tmp_path / "commands"
    bin_dir = tmp_path / "tool executables"
    fake_uv = tmp_path / "fake-bin/uv"
    executable(
        fake_uv,
        'if [ "$2" = "dir" ]; then printf "%s\\n" "$TEST_TOOL_BIN"; else printf "%s\\n" "$*" >> "$TEST_COMMANDS"; fi',
    )
    executable(bin_dir / "partlet", 'printf "%s\\n" "$*" >> "$TEST_COMMANDS"')
    env = {
        **os.environ,
        "PATH": f"{fake_uv.parent}:/usr/bin:/bin",
        "TEST_TOOL_BIN": str(bin_dir),
        "TEST_COMMANDS": str(commands),
    }
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/install.sh"), *arguments],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert commands.read_text().splitlines() == [
        f"tool install --no-config --python 3.12 --reinstall {ROOT}",
        setup_command,
    ]
