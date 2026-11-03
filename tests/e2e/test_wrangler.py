"""Actual review/publish/unpublish CLI with synthetic S3 and public Worker URLs.

S3 objects are mirrored exactly into Miniflare's local R2 between runs.
This verifies the interfaces, not Cloudflare's hosted S3/binding coherence.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from helpers import CLOUD_PREFIXES, GITHUB_FILE_VARS

from partlet.store import R2Store

pytestmark = pytest.mark.e2e
ROOT = Path(__file__).resolve().parents[2]


def request(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as response:
        return response.code, dict(response.headers), response.read()


class Runtime:
    def __init__(self, tmp, config):
        self.tmp, self.config = tmp, config
        self.mirror, self.persist = tmp / "mirror", tmp / "r2"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(CLOUD_PREFIXES) and key not in GITHUB_FILE_VARS
        }
        self.env.update(
            WRANGLER_SEND_METRICS="false",
            CLOUDFLARE_CF_FETCH_ENABLED="false",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            PAGER="cat",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.port, self.base = port, f"http://127.0.0.1:{port}"
        self.wrangler_config = tmp / "wrangler.toml"
        self.wrangler_config.write_text(
            'name = "partlet-e2e"\n'
            f"main = {json.dumps(str(ROOT / 'worker/src/index.ts'))}\n"
            'compatibility_date = "2026-10-01"\n'
            '[vars]\nSOURCE = "e2e"\n'
            '[[r2_buckets]]\nbinding = "BUCKET"\nbucket_name = "e2e-local"\n'
        )

    def run(self, *args, cwd=None, input=None, credentials=False, expected=0):
        env = dict(self.env)
        if credentials:
            env.update(
                PARTLET_R2_ENDPOINT=self.config.endpoint_url,
                PARTLET_R2_BUCKET=self.config.bucket,
                PARTLET_R2_ACCESS_KEY_ID=self.config.access_key_id,
                PARTLET_R2_SECRET_ACCESS_KEY=self.config.secret_access_key,
            )
        proc = subprocess.run(
            args,
            check=False,
            cwd=cwd or self.tmp,
            env=env,
            input=input,
            text=True,
            capture_output=True,
            timeout=120,
        )
        assert proc.returncode == expected, (
            args,
            proc.returncode,
            proc.stdout,
            proc.stderr,
        )
        return proc.stdout + proc.stderr

    def cli(self, command, *args, input=None, expected=0, consolidate=False):
        # Force the existing consolidation boundary to one pack in this
        # fixture so A/B/C fit within metadata's real 60-second freshness.
        # The CLI, storage backend and publication algorithms remain real.
        if consolidate:
            launch = (
                "-c",
                (
                    "from partlet import gitstatic; gitstatic.MAX_PACKS = 1; "
                    "from partlet.cli import main; raise SystemExit(main())"
                ),
            )
        else:
            launch = ("-m", "partlet.cli")
        return self.run(
            sys.executable,
            "-P",
            *launch,
            command,
            *map(str, args),
            input=input,
            expected=expected,
            credentials=command in ("publish", "unpublish"),
        )

    def seed(self, store):
        shutil.rmtree(self.mirror, ignore_errors=True)
        self.mirror.mkdir()
        for key in store.list(""):
            path = self.mirror.joinpath(*key.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(store.get(key))
        self.run(
            "node",
            str(ROOT / "worker/tools/seed-r2.mjs"),
            str(self.mirror),
            str(self.persist),
            "e2e-local",
        )

    @contextmanager
    def worker(self):
        log = self.tmp / "wrangler.log"
        with log.open("w") as output:
            proc = subprocess.Popen(
                [
                    str(ROOT / "worker/node_modules/.bin/wrangler"),
                    "dev",
                    "--local",
                    "--config",
                    str(self.wrangler_config),
                    "--persist-to",
                    str(self.persist),
                    "--port",
                    str(self.port),
                    "--ip",
                    "127.0.0.1",
                    "--inspector-port",
                    "0",
                ],
                cwd=self.tmp,
                env=self.env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                deadline = time.monotonic() + 45
                while True:
                    assert proc.poll() is None, log.read_text()
                    try:
                        if request(self.base + "/")[0] == 200:
                            break
                    except OSError:
                        pass
                    assert time.monotonic() < deadline, log.read_text()
                    time.sleep(0.1)
                yield self.base
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
                assert proc.poll() is not None


@contextmanager
def cached_metadata_proxy(upstream, cached, respect_cache=False):
    """Model captured metadata or a cache obeying the Worker's response policy."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = urlsplit(self.path).path
            response = cached.get(path) or request(upstream + self.path)
            status, headers, data = response
            policy = headers.get("Cache-Control", "")
            if respect_cache and "max-age=" in policy and "no-store" not in policy:
                cached[path] = response
            self.send_response(status)
            for key in ("Content-Type", "Cache-Control"):
                if key in headers:
                    self.send_header(key, headers[key])
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


@pytest.fixture
def runtime(tmp_path, r2_config):
    with ExitStack() as services:
        runtime = Runtime(tmp_path, r2_config)
        runtime.services = services
        yield runtime


def test_review_publish_clone_rapid_updates_and_unpublish(
    mono, tmp_path, r2_config, runtime
):
    store = R2Store(r2_config)
    mono.write("foo/README.md", "# Synthetic public project\n")
    mono.write("foo/src/a.py", "print('first')\n")
    mono.write("foo/docs/index.html/leaf.txt", "directory boundary\n")
    mono.write("private/never-public.txt", "private sentinel\n")
    mono.write(
        ".gitleaks.toml",
        '[extend]\nuseDefault = true\n\n[[rules]]\nid = "e2e-secret"\n'
        'description = "Synthetic e2e secret"\n'
        "regex = '''partlet-e2e-secret-[A-Z0-9]{24}'''\n",
    )
    mono.write(
        "partlet.toml",
        f'[site]\nsource = "e2e"\nbase_url = "{runtime.base}"\n'
        '\n[projects.foo]\npath = "foo"\ndescription = "Public synthetic export"\n',
    )
    mono.commit("create synthetic source and unapproved manifest")
    report = runtime.cli(
        "review", "foo", "--repo", mono.path, "--published-tip", "none", input="y\n"
    )
    assert "approved" in (mono.path / "partlet.toml").read_text()
    assert "never-public" not in report
    assert "differs from the version committed" in runtime.cli(
        "publish", "--repo", mono.path, expected=2
    )
    assert store.list("") == []
    mono.commit("commit reviewed approval")
    assert "published" in runtime.cli("publish", "--repo", mono.path)
    first = json.loads(store.get("e2e/p/foo/current"))
    first_packs = store.get("e2e/p/foo/git/objects/info/packs")
    runtime.seed(store)
    clone = tmp_path / "clone"
    with runtime.worker() as base:
        assert request(base + "/foo")[0] == 200
        assert b"Synthetic public" in request(base + "/foo")[2]
        assert request(base + "/foo/raw/src/a.py")[2] == b"print('first')\n"
        assert request(base + "/foo/tree/docs/index.html")[0] == 200
        assert request(base + "/foo/blob/src/a.py")[0] == 200
        assert request(base + "/foo/raw/never-public.txt")[0] == 404
        assert request(base + "/lock")[0] == 404
        with tarfile.open(
            fileobj=BytesIO(request(base + "/foo/archive/foo.tar.gz")[2])
        ) as tar:
            assert "foo/src/a.py" in tar.getnames()
        with zipfile.ZipFile(
            BytesIO(request(base + "/foo/archive/foo.zip")[2])
        ) as archive:
            assert "foo/src/a.py" in archive.namelist()
        cached = {
            path: request(base + path)
            for path in ("/foo/HEAD", "/foo/info/refs", "/foo/objects/info/packs")
        }
        assert cached["/foo/objects/info/packs"][2] == first_packs
        assert cached["/foo/objects/info/packs"][1]["Cache-Control"] == "no-store"
        # Warm only the old pack list in a compliant HTTP cache. The next
        # refs request will be fresh: caching the list could pair refs C
        # with packs A that cannot contain C, even if all packs are retained.
        cache_proxy = runtime.services.enter_context(
            cached_metadata_proxy(base, {}, respect_cache=True)
        )
        assert request(cache_proxy + "/foo/objects/info/packs")[2] == first_packs
        captured_at = time.monotonic()
        runtime.run("git", "clone", "-q", base + "/foo", str(clone))
        runtime.run("git", "clone", "-q", base + "/foo.git", str(tmp_path / "alias"))
    assert runtime.run("git", "rev-parse", "HEAD", cwd=clone).strip() == first["tip"]

    mono.write("foo/src/a.py", "print('incremental')\n")
    mono.commit("incremental public update")
    assert "published" in runtime.cli("publish", "--repo", mono.path)
    incremental_packs = store.get("e2e/p/foo/git/objects/info/packs")
    assert len(incremental_packs.decode().splitlines()) == 3  # two packs and blank
    incremental = json.loads(store.get("e2e/p/foo/current"))
    runtime.seed(store)
    with runtime.worker():
        runtime.run("git", "pull", "-q", "--ff-only", cwd=clone)
        assert (
            runtime.run("git", "rev-parse", "HEAD", cwd=clone).strip()
            == incremental["tip"]
        )

    for generation in (3, 4):
        mono.write("foo/src/a.py", f"print('generation {generation}')\n")
        mono.commit(f"public update {generation}")
        assert "published" in runtime.cli(
            "publish", "--repo", mono.path, consolidate=True
        )
    assert time.monotonic() - captured_at < 60, (
        "rapid publications exceeded metadata freshness"
    )
    latest = json.loads(store.get("e2e/p/foo/current"))
    retired = json.loads(store.get("e2e/p/foo/retired-packs.json"))
    assert retired, "A's pack must have left both current and previous pack sets"
    runtime.seed(store)
    with runtime.worker() as base:
        mixed_clone = tmp_path / "mixed-cache-clone"
        runtime.run("git", "clone", "-q", cache_proxy + "/foo", str(mixed_clone))
        assert (
            runtime.run("git", "rev-parse", "HEAD", cwd=mixed_clone).strip()
            == latest["tip"]
        )
        # A's cached metadata still produces a complete, ordinary clone
        # after B and C have consolidated away its pack from their lists.
        for line in first_packs.decode().splitlines():
            if line.startswith("P "):
                for ext in ("pack", "idx"):
                    name = line[2:].removesuffix(".pack") + "." + ext
                    assert request(base + "/foo/objects/pack/" + name)[0] == 200
        with cached_metadata_proxy(base, cached) as proxy:
            stale_clone = tmp_path / "cached-clone"
            runtime.run("git", "clone", "-q", proxy + "/foo", str(stale_clone))
        assert (
            runtime.run("git", "rev-parse", "HEAD", cwd=stale_clone).strip()
            == first["tip"]
        )
        runtime.run("git", "pull", "-q", "--ff-only", cwd=clone)
        assert (
            runtime.run("git", "rev-parse", "HEAD", cwd=clone).strip() == latest["tip"]
        )
        assert "generation 4" in (clone / "src/a.py").read_text()
        assert request(base + "/foo/raw/src/a.py")[2] == b"print('generation 4')\n"
        assert request(base + "/foo/retired-packs.json")[0] == 404
        # Review reads the published tip through the same public route.
        runtime.cli("review", "foo", "--repo", mono.path, input="n\n", expected=1)

    assert "unchanged" in runtime.cli("publish", "--repo", mono.path)
    before = {key: store.get(key) for key in store.list("")}
    secret = "partlet-e2e-secret-" + "A1B2C3D4E5F6G7H8I9J0K1L2"
    mono.write("foo/leaked.txt", secret + "\n")
    mono.commit("synthetic secret rejection")
    output = runtime.cli("publish", "--repo", mono.path, expected=1)
    assert "secret scan" in output and secret not in output
    assert before == {key: store.get(key) for key in store.list("")}
    runtime.cli(
        "review",
        "foo",
        "--repo",
        mono.path,
        "--published-tip",
        latest["tip"],
        input="y\n",
        expected=1,
    )

    mono.write("partlet.toml", f'[site]\nsource = "e2e"\nbase_url = "{runtime.base}"\n')
    mono.commit("remove project before retirement")
    runtime.cli("unpublish", "foo", "--repo", mono.path, "--yes")
    assert store.list("e2e/p/foo/") == []
    assert store.get("e2e/lock") is None
    runtime.seed(store)
    with runtime.worker() as base:
        assert request(base + "/foo")[0] == 404
        assert request(base + "/foo/info/refs")[0] == 404
        assert b"foo" not in request(base + "/_partlet/index.json")[2]
        runtime.run(
            "git", "clone", base + "/foo", str(tmp_path / "retired"), expected=128
        )
