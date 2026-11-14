"""Disposable previews render real exports without publication approval."""

import json
from pathlib import Path

import pytest
from helpers import export_tip

from partlet import cli, runtime, worker
from partlet.gitutil import git, git_out
from partlet.manifest import load_manifest
from partlet.store import LocalStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def configured(mono):
    mono.write("foo/README.md", "# Foo\n\n[Code](src/code.py)\n")
    mono.write("foo/src/code.py", "print('preview')\n")
    mono.write("private/notes.txt", "private content\n")
    mono.commit("source")
    mono.write(
        "partlet.toml",
        '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n'
        '[site.theme]\nname = "paper"\nmode = "dark"\n'
        '[projects.foo]\npath = "foo"\n',
    )
    return mono.path / "partlet.toml"


@pytest.fixture
def prepared(monkeypatch):
    monkeypatch.setattr(runtime, "worker_root", lambda: ROOT / "worker")


def test_preview_unapproved_project_has_real_pages_archives_and_clonable_history(
    mono, configured, prepared, monkeypatch, tmp_path, serve, capsys
):
    original = configured.read_bytes()
    head = git_out("rev-parse", "HEAD", cwd=mono.path)
    mono.write("foo/README.md", "uncommitted content must not appear\n")
    calls = []
    directories = []

    def run(command, *, cwd, env):
        directories.append(cwd)
        calls.append(command)
        assert "PARTLET_R2_SECRET_ACCESS_KEY" not in env
        assert "CLOUDFLARE_API_TOKEN" not in env
        if "seed-r2.mjs" not in command[1]:
            assert "--local" in command
            assert "--experimental-provision=false" in command
            assert command[command.index("--ip") + 1] == "127.0.0.1"
            return 0
        store = LocalStore(Path(command[2]))
        current = json.loads(store.get("s/p/foo/current"))
        prefix = f"s/p/foo/site/{current['build']}"
        page = store.get(f"{prefix}/index.html")
        assert b"# Foo" not in page  # Markdown was rendered.
        assert b"<h1>Foo</h1>" in page
        assert b'data-partlet-output-version="1"' in page
        assert b'data-partlet-revision="' + current["tip"].encode() + b'"' in page
        assert b"uncommitted content" not in page
        assert b"http://127.0.0.1:8899/foo" in page
        assert b"https://partlet.example" not in page
        assert b'data-theme="paper" data-mode="dark"' in page
        assert store.get(f"{prefix}/blob/src/code.py")
        assert store.get(f"{prefix}/tree/src/index.html")
        assert store.get(f"{prefix}/raw/src/code.py") == b"print('preview')\n"
        assert store.get(f"s/p/foo/archive/{current['tip']}.zip")
        theme = json.loads(store.get("s/site-theme.json"))
        assert store.get(f"s/static/themes/{theme['digest']}/style.css")
        assert not any("private" in key for key in store.list(""))
        with serve(Path(command[2])) as base:
            clone = tmp_path / "clone"
            git("clone", "-q", f"{base}/s/p/foo/git", str(clone), cwd=tmp_path)
        assert (clone / "README.md").read_text().startswith("# Foo")
        return 0

    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "test-secret")
    monkeypatch.setattr(worker, "_run", run)
    assert cli.main(["preview", "--repo", str(mono.path), "--port", "8899"]) == 0
    assert len(calls) == 2
    assert all(not directory.exists() for directory in directories)
    assert configured.read_bytes() == original
    assert load_manifest(configured).projects["foo"].approved is None
    assert git_out("rev-parse", "HEAD", cwd=mono.path) == head
    assert "publication approvals are unchanged" in capsys.readouterr().out
    # Ordinary builds retain their approval gate after preview.
    out = tmp_path / "ordinary-build"
    assert cli.main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert LocalStore(out).get("s/p/foo/current") is None


@pytest.mark.parametrize("port", ["0", "-1", "65536"])
def test_invalid_port_fails_before_reading_source(monkeypatch, port, capsys):
    monkeypatch.setattr(cli, "load_manifest", lambda path: pytest.fail("read manifest"))
    assert cli.main(["preview", "--port", port]) == 2
    assert "between 1 and 65535" in capsys.readouterr().err


def test_missing_tools_fail_before_export(mono, configured, monkeypatch, capsys):
    def missing():
        raise runtime.SetupError("run `partlet setup --worker`")

    monkeypatch.setattr(runtime, "worker_root", missing)
    monkeypatch.setattr(cli, "check_tools", lambda **kw: pytest.fail("started build"))
    assert cli.main(["preview", "--repo", str(mono.path)]) == 2
    assert "partlet setup --worker" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", [17, KeyboardInterrupt(), OSError("cannot start")])
def test_server_failure_or_interrupt_cleans_disposable_data(
    mono, configured, prepared, monkeypatch, outcome, capsys
):
    directories = []

    def run(command, *, cwd, env):
        directories.append(cwd.parents[2])
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(worker, "_run", run)
    expected = (
        130
        if isinstance(outcome, KeyboardInterrupt)
        else 2
        if isinstance(outcome, OSError)
        else 17
    )
    assert cli.main(["preview", "--repo", str(mono.path)]) == expected
    assert directories and all(not directory.exists() for directory in directories)
    assert "Traceback" not in capsys.readouterr().err


def test_bad_project_prevents_server_start(
    mono, configured, prepared, monkeypatch, capsys
):
    configured.write_text(
        configured.read_text().replace('path = "foo"', 'path = "missing"')
    )
    monkeypatch.setattr(worker, "_run", lambda *a, **kw: pytest.fail("server started"))
    assert cli.main(["preview", "--repo", str(mono.path)]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_optional_scan_blocks_secrets_before_serving(
    mono, configured, prepared, monkeypatch, capsys
):
    token = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"
    mono.write("foo/config.py", f'TOKEN = "{token}"\n')
    mono.commit("synthetic secret")
    monkeypatch.setattr(worker, "_run", lambda *a, **kw: pytest.fail("server started"))
    assert cli.main(["preview", "--repo", str(mono.path), "--scan"]) == 2
    output = capsys.readouterr()
    assert "secret scan found" in output.err
    assert token not in output.err + output.out


def test_preview_includes_stale_approval_without_changing_it(
    mono, tmp_path, configured, prepared, monkeypatch
):
    tip = export_tip(mono, tmp_path)
    configured.write_text(configured.read_text() + f'approved = "{tip}"\n')
    original = configured.read_bytes()
    git("checkout", "-q", "--orphan", "rewritten", cwd=mono.path)
    mono.write("foo/README.md", "# Rewritten\n")
    mono.commit("new history")
    git("branch", "-M", "main", cwd=mono.path)
    monkeypatch.setattr(worker, "_run", lambda *a, **kw: 0)
    assert cli.main(["preview", "--repo", str(mono.path)]) == 0
    assert configured.read_bytes() == original


def test_alternate_manifest_and_branch_control_preview_inputs(
    mono, tmp_path, configured, prepared, monkeypatch
):
    mono.commit("manifest shared by both branches")
    git("checkout", "-q", "-b", "preview-source", cwd=mono.path)
    mono.write("foo/README.md", "# Alternate branch\n")
    mono.commit("alternate source")
    git("checkout", "-q", "main", cwd=mono.path)
    alternate = tmp_path / "alternate.toml"
    alternate.write_text(
        configured.read_text().replace(
            'source = "s"', 'source = "alternate"\nbranch = "preview-source"'
        )
    )
    inspected = []

    def run(command, *, cwd, env):
        if "seed-r2.mjs" in command[1]:
            store = LocalStore(Path(command[2]))
            current = json.loads(store.get("alternate/p/foo/current"))
            page = store.get(f"alternate/p/foo/site/{current['build']}/index.html")
            assert b"<h1>Alternate branch</h1>" in page
            inspected.append(True)
        return 0

    monkeypatch.setattr(worker, "_run", run)
    assert (
        cli.main(["preview", "--repo", str(mono.path), "--manifest", str(alternate)])
        == 0
    )
    assert inspected
    assert git_out("branch", "--show-current", cwd=mono.path) == "main"


def test_no_projects_reports_setup_hint(
    mono, configured, prepared, monkeypatch, capsys
):
    configured.write_text('[site]\nsource = "s"\nbase_url = "https://example.com"\n')
    monkeypatch.setattr(cli, "check_tools", lambda **kw: pytest.fail("started build"))
    assert cli.main(["preview", "--repo", str(mono.path)]) == 2
    assert "add [projects.NAME]" in capsys.readouterr().err
