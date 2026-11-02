import json
import os
import signal
import subprocess
import sys
import time

import pytest
from helpers import FAKE_R2_SECRET, export_tip, mirror_store

from partlet.cli import main
from partlet.gitutil import git
from partlet.store import R2Store

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


def write_manifest(mono, approved, extra=""):
    mono.write(
        "partlet.toml",
        f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
{extra}
""",
    )
    mono.commit("manifest")  # touches nothing under foo/: the export tip stays


@pytest.fixture
def approved(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    tip = export_tip(mono, tmp_path)
    write_manifest(mono, tip)
    return tip


@pytest.fixture
def publish(tmp_path, monkeypatch, request):
    """Run `partlet publish` with credentials for the moto bucket, if any.

    The keys are set before every run, because each run removes them from
    the environment.
    """

    def run(mono, secret=None):
        if "r2_env" in request.fixturenames:
            config = request.getfixturevalue("r2_env")
            monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", config.access_key_id)
            monkeypatch.setenv(
                "PARTLET_R2_SECRET_ACCESS_KEY", secret or config.secret_access_key
            )
        summary = tmp_path / f"summary-{len(list(tmp_path.glob('summary-*')))}.md"
        code = main(["publish", "--repo", str(mono.path), "--summary", str(summary)])
        return code, summary.read_text() if summary.exists() else ""

    return run


def test_publish_to_r2_then_clone_and_pull(
    mono, tmp_path, r2_env, approved, serve, publish
):
    code, summary = publish(mono)
    assert code == 0
    assert "| foo | published |" in summary
    assert "gitleaks 8.30.1" in summary
    store = R2Store(r2_env)
    assert store.get("s/lock") is None
    mirror_store(store, tmp_path / "site-1")
    clone = tmp_path / "clone"
    with serve(tmp_path / "site-1") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(clone), cwd=tmp_path)

    mono.write("foo/b.txt", "two\n")
    mono.commit("c2")
    assert publish(mono)[0] == 0
    mirror_store(store, tmp_path / "site-2")
    with serve(tmp_path / "site-2") as base:
        git("pull", "-q", "--ff-only", f"{base}/s/p/foo/git", "main", cwd=clone)
    assert (clone / "b.txt").read_text() == "two\n"


def test_publish_removes_the_keys_from_the_environment(
    mono, tmp_path, r2_env, approved, publish
):
    assert publish(mono)[0] == 0
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in os.environ
    assert "PARTLET_R2_ACCESS_KEY_ID" not in os.environ


def test_secret_never_reaches_output(
    mono, tmp_path, r2_env, approved, capsys, monkeypatch, publish
):
    assert publish(mono)[0] == 0
    # And a failing run, against a bucket that does not exist.
    monkeypatch.setenv("PARTLET_R2_BUCKET", "partlet-no-such-bucket")
    code, summary = publish(mono, secret=FAKE_R2_SECRET)
    assert code == 1
    out = capsys.readouterr()
    for text in (out.out, out.err, summary):
        assert FAKE_R2_SECRET not in text


def test_build_also_drops_the_keys(mono, tmp_path, approved, monkeypatch):
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", FAKE_R2_SECRET)
    out = tmp_path / "out"
    assert main(["build", "--scan", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in os.environ


def test_missing_credentials(mono, tmp_path, approved, capsys, publish):
    assert publish(mono)[0] == 2
    assert "PARTLET_R2_BUCKET" in capsys.readouterr().err


def test_refuses_a_checkout_of_another_branch(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    git("checkout", "-q", "-b", "feature", cwd=mono.path)
    mono.write("other.txt", "x\n")
    mono.commit("feature work")
    assert publish(mono)[0] == 2
    assert "HEAD is" in capsys.readouterr().err


def test_refuses_without_a_local_publishing_branch(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    # What a pull_request checkout looks like: detached HEAD, no refs/heads/main.
    git("checkout", "-q", "--detach", cwd=mono.path)
    git("branch", "-q", "-D", "main", cwd=mono.path)
    assert publish(mono)[0] == 2
    assert "branch 'main' not found" in capsys.readouterr().err


def test_refuses_an_uncommitted_manifest_edit(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    text = (mono.path / "partlet.toml").read_text()
    (mono.path / "partlet.toml").write_text(text + "\n# edited\n")
    assert publish(mono)[0] == 2
    assert "differs from the version committed" in capsys.readouterr().err


def test_ci_enforces_the_approval_pin_and_fast_forward(
    mono, tmp_path, r2_env, approved, publish
):
    assert publish(mono)[0] == 0

    # Rewrite the monorepo's history, so foo's published tip is no longer an
    # ancestor of its export. The manifest still carries the old approval.
    git("checkout", "-q", "--orphan", "rewritten", cwd=mono.path)
    mono.write("foo/README.md", "# Foo, rewritten\n")
    mono.commit("c1 again")
    git("branch", "-q", "-M", "main", cwd=mono.path)
    code, summary = publish(mono)
    assert code == 1
    assert "| foo | failed |" in summary
    assert "history rewrite" in summary


def test_secret_blocks_the_publish(mono, tmp_path, r2_env, publish):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    write_manifest(mono, export_tip(mono, tmp_path))
    code, summary = publish(mono)
    assert code == 1
    assert "secret scan: 1 finding(s)" in summary
    assert FAKE_TOKEN not in summary
    assert R2Store(r2_env).list("s/p/") == []


def test_a_held_lock_stops_the_publish(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    held = json.dumps({"holder": "another run", "since": "2026-10-17T00:00:00+00:00"})
    R2Store(r2_env).put("s/lock", held.encode())
    code, _ = publish(mono)
    assert code == 1
    assert "locked by another run" in capsys.readouterr().err
    assert R2Store(r2_env).list("s/p/") == []


def test_summary_write_failure_reports_error_and_releases_lock(
    mono, tmp_path, approved, capsys
):
    out = tmp_path / "out"
    code = main(
        [
            "build",
            "--repo",
            str(mono.path),
            "--out",
            str(out),
            "--summary",
            str(tmp_path / "missing" / "summary.md"),
        ]
    )
    assert code == 1
    assert "cannot write summary" in capsys.readouterr().err
    assert not (out / "s" / "lock").exists()


def test_local_store_write_failure_is_a_normal_failed_run(
    mono, tmp_path, approved, capsys
):
    out = tmp_path / "out"
    out.write_text("a file cannot be a store directory")
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 1
    assert "partlet:" in capsys.readouterr().err


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT, signal.SIGKILL])
def test_real_process_interruption_and_explicit_recovery(
    mono, tmp_path, approved, stop_signal
):
    """Catchable signals release locks; a killed process requires unlock."""
    script = """
import signal
import sys
from pathlib import Path
from partlet import cli
def waiting(*args):
    Path(sys.argv[3]).write_text("ready")
    while True:
        signal.pause()
cli.publish_all = waiting
sys.exit(cli.main(["build", "--repo", sys.argv[1], "--out", sys.argv[2]]))
"""
    out, ready = tmp_path / "out", tmp_path / "ready"
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(mono.path), str(out), str(ready)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while (
            not ready.exists() and proc.poll() is None and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert ready.exists(), proc.communicate(timeout=1)
        assert (out / "s" / "lock").exists()
        proc.send_signal(stop_signal)
        proc.communicate(timeout=10)
        assert proc.returncode != 0
        lock = out / "s" / "lock"
        if stop_signal == signal.SIGKILL:
            assert lock.exists()
            # The holder is confirmed stopped by communicate() above.
            assert (
                main(["unlock", "--repo", str(mono.path), "--out", str(out), "--yes"])
                == 0
            )
        assert not lock.exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)
