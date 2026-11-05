"""The preview CLI serves a disposable site through the actual local Worker."""

import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from partlet import runtime
from partlet.gitutil import git

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_preview_cli_browses_clones_and_cleans_on_shutdown(
    mono, tmp_path, monkeypatch, stop_signal
):
    mono.write("foo/README.md", "# Local preview\n")
    mono.write("foo/src/code.py", "print('hello')\n")
    mono.write("private/notes.txt", "keep private\n")
    mono.commit("source")
    mono.write(
        "partlet.toml",
        '[site]\nsource = "preview-test"\nbase_url = "https://public.example"\n'
        '[site.theme]\nname = "terminal"\nmode = "dark"\n'
        '[projects.foo]\npath = "foo"\n',
    )
    original = (mono.path / "partlet.toml").read_bytes()
    # Prepare an isolated managed runtime from the already-installed dev tools.
    # No downloads or user tool installation are needed, and the CLI's real
    # runtime discovery, asset selection and all Worker invocations still run.
    monkeypatch.setenv("PARTLET_DATA_DIR", str(tmp_path / "data"))
    destination = runtime._worker_destination()
    destination.mkdir(parents=True)
    assets = runtime.asset_root() / "worker"
    for source in runtime._worker_files():
        target = destination / source.relative_to(assets)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    (destination / "node_modules").symlink_to(ROOT / "worker/node_modules")
    (destination / ".complete").touch()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env = dict(os.environ, TMPDIR=str(temporary))
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    log = tmp_path / "preview.log"

    def fetch(path):
        with urllib.request.urlopen(base + path, timeout=5) as response:
            return response.read()

    with log.open("w+") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "partlet.cli",
                "preview",
                "--repo",
                str(mono.path),
                "--port",
                str(port),
            ],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                assert process.poll() is None, log.read_text()
                try:
                    if b"foo" in fetch("/"):
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.1)
            else:
                pytest.fail(f"preview did not become ready: {log.read_text()}")
            page = fetch("/foo/")
            assert b"<h1>Local preview</h1>" in page
            assert f"{base}/foo".encode() in page
            assert b'data-theme="terminal" data-mode="dark"' in page
            stylesheet = re.search(rb'href="(/_partlet/themes/[^\"]+/style.css)"', page)
            assert stylesheet and fetch(stylesheet[1].decode())
            assert b"code.py" in fetch("/foo/tree/src")
            assert b"print" in fetch("/foo/blob/src/code.py")
            assert fetch("/foo/raw/src/code.py") == b"print('hello')\n"
            with ZipFile(BytesIO(fetch("/foo/archive/foo.zip"))) as archive:
                assert any(name.endswith("src/code.py") for name in archive.namelist())
            clone = tmp_path / "clone"
            git("clone", "-q", f"{base}/foo", str(clone), cwd=tmp_path)
            assert (clone / "README.md").read_text() == "# Local preview\n"
            assert not (clone / "private").exists()
            assert (mono.path / "partlet.toml").read_bytes() == original
            assert list(temporary.glob("partlet-preview-*"))
            process.send_signal(stop_signal)
            process.wait(timeout=15)
            assert process.returncode == (
                130 if stop_signal == signal.SIGINT else 128 + signal.SIGTERM
            )
            assert not list(temporary.glob("partlet-preview-*"))
            with pytest.raises((OSError, urllib.error.URLError)):
                fetch("/")
            assert "Traceback" not in log.read_text()
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
