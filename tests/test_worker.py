"""Installed Worker commands use only the selected config and local runtime."""

import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from partlet import __version__, worker
from partlet.cli import main


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    class SetupError(Exception):
        pass

    root = tmp_path / "runtime"
    root.mkdir()
    stub = SimpleNamespace(
        asset_root=lambda: Path(__file__).resolve().parents[1],
        worker_root=lambda: root,
        SetupError=SetupError,
    )
    monkeypatch.setattr(worker, "_runtime", lambda: stub)
    return stub


@pytest.fixture
def config(runtime, tmp_path):
    return worker.init_config(
        tmp_path / "site",
        name="personal",
        source="my-monorepo",
        bucket="my-public-bucket",
        domain="code.example.com",
    )


def change(config, old, new):
    config.write_text(config.read_text().replace(old, new))


def capture_runs(monkeypatch, *, result=0):
    calls = []

    def run(command, *, cwd, env):
        effective = cwd / "wrangler.toml"
        calls.append(
            (
                command,
                cwd,
                env,
                tomllib.loads(effective.read_text()) if effective.exists() else None,
            )
        )
        return result

    monkeypatch.setattr(worker, "_run", run)
    return calls


def test_init_two_independent_configs_have_no_install_paths(runtime, tmp_path):
    for name in ("personal", "work"):
        path = tmp_path / name
        assert (
            main(
                [
                    "worker",
                    "init",
                    str(path),
                    "--name",
                    name,
                    "--source",
                    name,
                    "--bucket",
                    f"{name}-public",
                    "--domain",
                    f"{name}.example.com",
                ]
            )
            == 0
        )
        config = worker.load_config(path / "wrangler.toml", deploy=True)
        assert config.name == name
        assert config.source == name
        assert "main" not in config.data
        assert not config.data["workers_dev"]
        assert not config.data["preview_urls"]
        assert (path / ".gitignore").read_text() == ".partlet/\n"


@pytest.mark.parametrize("filename", ["wrangler.toml", ".gitignore"])
@pytest.mark.parametrize("symlink", [True, False])
def test_init_never_replaces_existing_files(runtime, tmp_path, filename, symlink):
    directory = tmp_path / "site"
    directory.mkdir()
    target = directory / filename
    if symlink:
        target.symlink_to(tmp_path / "missing")
    else:
        target.write_text("preserve me")
    assert main(["worker", "init", str(directory)]) == 2
    if symlink:
        assert target.is_symlink()
    else:
        assert target.read_text() == "preserve me"


def test_init_without_options_has_actionable_placeholders(runtime, tmp_path):
    path = worker.init_config(tmp_path / "site")
    with pytest.raises(worker.WorkerError, match="SOURCE"):
        worker.load_config(path)


def test_init_workers_dev_has_no_custom_domain(runtime, tmp_path, capsys):
    directory = tmp_path / "workers-dev"
    assert (
        main(
            [
                "worker",
                "init",
                str(directory),
                "--workers-dev",
                "--name",
                "personal",
                "--source",
                "my-monorepo",
                "--bucket",
                "my-public-bucket",
            ]
        )
        == 0
    )
    config = worker.load_config(directory / "wrangler.toml", deploy=True)
    assert config.data["workers_dev"] is True
    assert config.data["preview_urls"] is False
    assert "routes" not in config.data
    assert config.domains == ()
    assert "domain before deploying" not in capsys.readouterr().out


def test_init_workers_dev_and_domain_are_mutually_exclusive(runtime, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "worker",
                "init",
                str(tmp_path / "site"),
                "--workers-dev",
                "--domain",
                "code.example.com",
            ]
        )
    assert exc.value.code == 2
    assert not (tmp_path / "site").exists()
    with pytest.raises(worker.WorkerError, match="either"):
        worker.init_config(
            tmp_path / "site", domain="code.example.com", workers_dev=True
        )


@pytest.mark.parametrize("workers_dev", [None, False, True])
def test_deployment_without_routes_requires_workers_dev(config, workers_dev):
    text = config.read_text().split("[[routes]]")[0]
    if workers_dev is None:
        text = text.replace("workers_dev = false\n", "")
    elif workers_dev:
        text = text.replace("workers_dev = false", "workers_dev = true")
    config.write_text(text)
    if workers_dev:
        assert worker.load_config(config, deploy=True).domains == ()
    else:
        with pytest.raises(worker.WorkerError, match="route or workers_dev"):
            worker.load_config(config, deploy=True)


def test_preview_urls_do_not_replace_a_public_site_address(config):
    config.write_text(
        config.read_text()
        .split("[[routes]]")[0]
        .replace("preview_urls = false", "preview_urls = true")
    )
    with pytest.raises(worker.WorkerError, match="route or workers_dev"):
        worker.load_config(config, deploy=True)


def test_workers_dev_cancellation_reports_real_target_identity(
    runtime, tmp_path, monkeypatch, capsys
):
    config = worker.init_config(
        tmp_path / "site",
        name="personal",
        source="my-monorepo",
        bucket="my-public-bucket",
        workers_dev=True,
        account_id="a" * 32,
    )
    calls = capture_runs(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(["worker", "deploy", "--config", str(config)]) == 1
    output = capsys.readouterr().out
    for identity in (
        "Billable",
        "personal",
        "my-monorepo",
        "my-public-bucket",
        "a" * 32,
        "workers.dev",
    ):
        assert identity in output
    assert "https://personal" not in output
    assert not calls


def test_workers_dev_and_custom_domain_remain_valid_together(config):
    change(config, "workers_dev = false", "workers_dev = true")
    loaded = worker.load_config(config, deploy=True)
    assert loaded.domains == ("code.example.com",)
    assert loaded.data["workers_dev"] is True


def test_init_expands_home_before_refusing_directory_symlinks(
    runtime, tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "site-link").symlink_to(elsewhere, target_is_directory=True)
    assert main(["worker", "init", "~/site-link"]) == 2
    assert list(elsewhere.iterdir()) == []


def test_init_with_missing_assets_has_no_traceback(runtime, tmp_path, capsys):
    def missing():
        raise runtime.SetupError("Partlet assets are missing; reinstall Partlet")

    runtime.asset_root = missing
    assert main(["worker", "init", str(tmp_path / "site")]) == 2
    assert "reinstall Partlet" in capsys.readouterr().err


def test_installed_cli_reports_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"partlet {__version__}"


@pytest.mark.parametrize(
    "extra",
    [
        '\nmain = "other-worker.js"\n',
        '\n[build]\ncommand = "create-a-resource"\n',
        '\n[assets]\ndirectory = "public"\n',
        '\n[env.production]\nname = "other-worker"\n',
    ],
)
def test_reject_unsupported_config_before_invoking_wrangler(config, monkeypatch, extra):
    # Prefix top-level main before the existing tables; other sections append.
    if extra.lstrip().startswith("main"):
        config.write_text(extra + config.read_text())
    else:
        config.write_text(config.read_text() + extra)
    calls = capture_runs(monkeypatch)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 2
    assert calls == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('bucket_name = "my-public-bucket"', 'bucket_name = "replace-me"'),
        ('SOURCE = "my-monorepo"', 'SOURCE = "../private"'),
        ('SOURCE = "my-monorepo"', 'SOURCE = ["bad"]'),
        ('binding = "BUCKET"', 'binding = "OTHER"'),
        ('binding = "BUCKET"', 'binding = "BUCKET"\nremote = true'),
        ("custom_domain = true", "custom_domain = false"),
        ('pattern = "code.example.com"', 'pattern = "https://code.example.com/path"'),
        ('name = "personal"', 'name = "worker/path"'),
        ('compatibility_date = "2026-10-01"', 'compatibility_date = "2026-99-99"'),
    ],
)
def test_invalid_config_fails_before_process(config, monkeypatch, old, new):
    change(config, old, new)
    calls = capture_runs(monkeypatch)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 2
    assert calls == []


def test_dry_run_uses_installed_code_cleans_credentials_and_preserves_config(
    config, runtime, monkeypatch, tmp_path
):
    original = config.read_bytes()
    (config.parent / ".env").write_text("CLOUDFLARE_API_TOKEN=not-real\n")
    (config.parent / ".dev.vars").write_text("SOURCE=wrong-source\n")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "not-real")
    monkeypatch.setenv("CF_ACCOUNT_ID", "not-real")
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "not-real")
    monkeypatch.setenv("WRANGLER_ENV", "production")
    monkeypatch.chdir(tmp_path)
    calls = capture_runs(monkeypatch)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 0
    command, cwd, env, effective = calls[0]
    assert command[1:3] == ["deploy", str(runtime.worker_root() / "src" / "index.ts")]
    assert "--dry-run" in command
    assert "--autoconfig=false" in command
    assert "--experimental-provision=false" in command
    assert "--experimental-auto-create=false" in command
    assert not cwd.exists()
    assert effective["vars"] == {"SOURCE": "my-monorepo"}
    assert effective["r2_buckets"][0]["bucket_name"] == "my-public-bucket"
    assert not any(
        key.startswith(("CLOUDFLARE_API", "CF_", "PARTLET_R2_", "WRANGLER_ENV"))
        for key in env
    )
    assert env["WRANGLER_SEND_METRICS"] == "false"
    assert env["CLOUDFLARE_CF_FETCH_ENABLED"] == "false"
    assert config.read_bytes() == original


def test_deployment_requires_confirmation_and_reports_billable_target(
    config, monkeypatch, capsys
):
    calls = capture_runs(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(["worker", "deploy", "--config", str(config)]) == 1
    output = capsys.readouterr().out
    assert "Billable" in output
    assert "personal" in output
    assert "my-public-bucket" in output
    assert "code.example.com" in output
    assert not calls


def test_explicit_confirmation_passes_cloudflare_auth_but_not_publisher_keys(
    config, monkeypatch
):
    calls = capture_runs(monkeypatch, result=17)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "not-real")
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "not-real")
    assert main(["worker", "deploy", "--config", str(config), "--yes"]) == 17
    assert calls[0][2]["CLOUDFLARE_API_TOKEN"] == "not-real"
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in calls[0][2]


def test_preview_seeds_only_fresh_isolated_state(config, monkeypatch, tmp_path):
    out = tmp_path / "built"
    (out / "my-monorepo" / "p").mkdir(parents=True)
    calls = capture_runs(monkeypatch)
    for _ in range(2):
        assert (
            main(["worker", "preview", "--config", str(config), "--out", str(out)]) == 0
        )
    first_seed, first_server, second_seed, _ = calls
    assert first_seed[0][-1] == "my-public-bucket"
    assert first_seed[0][2] == str(out)
    assert first_seed[1] != second_seed[1]
    assert first_seed[1].parent == config.parent / ".partlet"
    assert first_seed[1] == first_server[1]
    assert not first_seed[1].exists()
    assert "--local" in first_server[0]
    assert "127.0.0.1" in first_server[0]
    assert "--persist-to" in first_server[0]
    assert "--inspector-port" in first_server[0]


def test_preview_seed_failure_does_not_start_server(config, monkeypatch, tmp_path):
    out = tmp_path / "built"
    (out / "my-monorepo").mkdir(parents=True)
    calls = capture_runs(monkeypatch, result=19)
    assert main(["worker", "preview", "--config", str(config), "--out", str(out)]) == 19
    assert len(calls) == 1
    assert not calls[0][1].exists()


def test_preview_rejects_other_sources_before_seed(config, monkeypatch, tmp_path):
    calls = capture_runs(monkeypatch)
    assert (
        main(["worker", "preview", "--config", str(config), "--out", str(tmp_path)])
        == 2
    )
    assert not calls


def test_symlinked_state_is_never_used(config, monkeypatch, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (config.parent / ".partlet").symlink_to(elsewhere, target_is_directory=True)
    calls = capture_runs(monkeypatch)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 2
    assert not calls
    assert list(elsewhere.iterdir()) == []


def test_missing_runtime_has_setup_advice(config, runtime, capsys):
    def unavailable():
        raise runtime.SetupError("run partlet setup --worker")

    runtime.worker_root = unavailable
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 2
    assert "partlet setup --worker" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["login", "whoami"])
def test_account_commands_use_prepared_runtime(runtime, monkeypatch, command):
    calls = capture_runs(monkeypatch, result=7)
    assert main(["worker", command]) == 7
    assert calls[0][0][1:] == [command]
    assert calls[0][1] == runtime.worker_root()


def test_process_failure_is_a_cli_error(config, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise OSError("cannot start Wrangler")

    monkeypatch.setattr(worker, "_run", fail)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 2
    assert "cannot start Wrangler" in capsys.readouterr().err


def test_ctrl_c_stops_worker_without_traceback(config, monkeypatch, capsys):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker, "_run", interrupt)
    assert main(["worker", "deploy", "--config", str(config), "--dry-run"]) == 130
    assert capsys.readouterr().err == "Worker command stopped.\n"


def test_interrupted_process_is_terminated_and_waited(monkeypatch, tmp_path):
    events = []

    class Process:
        def terminate(self):
            events.append("terminate")

        def kill(self):
            events.append("kill")

    process = Process()
    waits = iter([KeyboardInterrupt(), subprocess.TimeoutExpired("wrangler", 5), 0])

    def wait(timeout=None):
        events.append(("wait", timeout))
        result = next(waits)
        if isinstance(result, BaseException):
            raise result
        return result

    process.wait = wait
    monkeypatch.setattr(worker.subprocess, "Popen", lambda *args, **kwargs: process)
    with pytest.raises(KeyboardInterrupt):
        worker._run(["fake-wrangler"], cwd=tmp_path, env={})
    assert events == [("wait", None), "terminate", ("wait", 5), "kill", ("wait", None)]
