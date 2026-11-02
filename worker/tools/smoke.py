"""Actual publisher -> local R2 -> Wrangler HTTP clone and incremental pull.

Every repository, Git configuration, port and persistence directory belongs
only to this run. This is synthetic/local evidence, never a cloud check.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="partlet-worker-smoke-") as temporary:
        tmp = Path(temporary)
        home = tmp / "home"
        home.mkdir()
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GIT_", "CLOUDFLARE_", "CF_", "WRANGLER_"))
        }
        environment.update(
            HOME=str(home),
            XDG_CONFIG_HOME=str(home / "config"),
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            WRANGLER_SEND_METRICS="false",
            CLOUDFLARE_CF_FETCH_ENABLED="false",
        )
        mono, out, persist = tmp / "mono", tmp / "out", tmp / "r2"
        clone = tmp / "clone"
        log = tmp / "wrangler.log"
        # Reserve an unused port, then immediately launch Wrangler on it.
        # The readiness loop diagnoses an intervening collision as failure.
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        # A synthetic config beside an empty environment avoids loading any
        # developer .dev.vars/.env or account-specific Wrangler settings.
        config = tmp / "wrangler.toml"
        config.write_text(
            'name = "partlet-smoke"\n'
            f"main = {json.dumps(str(root / 'worker/src/index.ts'))}\n"
            'compatibility_date = "2026-10-01"\n'
            '[vars]\nSOURCE = "smoke"\n'
            '[[r2_buckets]]\nbinding = "BUCKET"\nbucket_name = "replace-me"\n',
            encoding="utf-8",
        )

        def run(*args: str, cwd: Path = tmp) -> str:
            result = subprocess.run(
                args,
                cwd=cwd,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    f"command failed ({result.returncode}): {args!r}\n"
                    f"{result.stdout}\n{result.stderr}"
                )
            return result.stdout.strip()

        def git(*args: str, cwd: Path = mono) -> str:
            return run("git", *args, cwd=cwd)

        def write(path: str, data: str) -> None:
            target = mono / "foo" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(data, encoding="utf-8")

        git("init", "-q", "-b", "main", str(mono), cwd=tmp)
        git("config", "user.email", "synthetic@example.invalid")
        git("config", "user.name", "Synthetic Publisher")
        git("config", "commit.gpgsign", "false")
        write("README.md", "# Synthetic project\n\n<script>alert(1)</script>\n")
        write("sp ace/f #1?%.txt", "one\n")
        write("docs/index.html/leaf.txt", "directory sentinel\n")
        write("docs/children/index.html/leaf.txt", "nested child sentinel\n")
        write("docs/a!'()*~%é/leaf.txt", "Unicode sentinel\n")
        write("evil.html", "<script>window.secret = 'executed'</script>\n")
        write(
            "evil.svg", '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>\n'
        )
        write("evil.js", "alert(1)\n")
        write("deceptive.png", "<script>alert(1)</script>\n")
        git("add", "-A")
        git("commit", "-qm", "first synthetic publication")

        # The approval is computed from a throwaway export, never a real repo.
        code = (
            "from pathlib import Path; from partlet.export import export_project; "
            "from partlet.manifest import Project; import sys; "
            "print(export_project(Path(sys.argv[1]), 'main', "
            "Project('foo', 'foo'), Path(sys.argv[2])))"
        )
        approved = run(sys.executable, "-c", code, str(mono), str(tmp / "probe.git"))
        (mono / "partlet.toml").write_text(
            f'[site]\nsource = "smoke"\nbase_url = "{base}"\n\n'
            f'[projects.foo]\npath = "foo"\napproved = "{approved}"\n',
            encoding="utf-8",
        )
        git("add", "-A")
        git("commit", "-qm", "approve synthetic export")

        def publish() -> dict:
            output = run(
                sys.executable,
                "-m",
                "partlet.cli",
                "build",
                "--repo",
                str(mono),
                "--out",
                str(out),
            )
            print(output, flush=True)
            record = json.loads((out / "smoke/p/foo/current").read_text())
            run("node", str(root / "worker/tools/seed-r2.mjs"), str(out), str(persist))
            return record

        def request(path: str, method: str = "GET", headers: dict | None = None):
            request = urllib.request.Request(
                base + path, method=method, headers=headers or {}
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, response.headers, response.read()
            except urllib.error.HTTPError as response:
                return response.code, response.headers, response.read()

        def require(condition: bool, detail: str) -> None:
            if not condition:
                raise AssertionError(detail)

        process = None
        log_stream = None

        def stop() -> None:
            nonlocal process, log_stream
            if process is not None:
                # Kill only this run's process group, including workerd.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                process = None
            if log_stream is not None:
                log_stream.close()
                log_stream = None

        def start() -> None:
            nonlocal process, log_stream
            log_stream = log.open("ab")
            process = subprocess.Popen(
                [
                    str(root / "worker/node_modules/.bin/wrangler"),
                    "dev",
                    "--config",
                    str(config),
                    "--local",
                    "--ip",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--inspector-port",
                    "0",
                    "--var",
                    "SOURCE:smoke",
                    "--persist-to",
                    str(persist),
                    "--show-interactive-dev-session=false",
                ],
                cwd=tmp,
                env=environment,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Wrangler exited:\n" + log.read_text())
                try:
                    if request("/_partlet/style.css")[0] == 200:
                        return
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.2)
            raise RuntimeError("Wrangler readiness timeout:\n" + log.read_text())

        try:
            first = publish()
            start()
            git("clone", "-q", f"{base}/foo", str(clone), cwd=tmp)
            require(
                git("rev-parse", "HEAD", cwd=clone) == first["tip"],
                "clone tip mismatch",
            )
            for path in (
                "/",
                "/foo",
                "/foo.git",
                "/foo/tree/docs",
                "/foo/tree/docs/index.html",
                "/foo/tree/docs/children/index.html",
                "/foo/tree/docs/a%21%27%28%29%2A~%25%C3%A9",
                "/foo/blob/sp%20ace/f%20%231%3F%25.txt",
            ):
                status, headers, body = request(path)
                require(status == 200, f"publisher URL not served: {path} ({status})")
                require(
                    headers["Content-Type"] == "text/html; charset=utf-8",
                    f"page type: {path}",
                )
                if path == "/foo":
                    require(
                        b"<script>alert(1)</script>" not in body,
                        "README HTML was not escaped",
                    )
            for path, content_type in (
                ("evil.html", "application/octet-stream"),
                ("evil.svg", "application/octet-stream"),
                ("evil.js", "text/plain; charset=utf-8"),
                ("deceptive.png", "image/png"),
            ):
                status, headers, _body = request(f"/foo/raw/{path}")
                require(
                    status == 200 and headers["Content-Type"] == content_type,
                    f"raw type: {path}",
                )
                require(
                    "sandbox" in headers["Content-Security-Policy"],
                    f"raw sandbox: {path}",
                )
                require(
                    headers["X-Content-Type-Options"] == "nosniff",
                    f"raw sniffing: {path}",
                )
            status, _headers, body = request("/foo/raw/sp%20ace/f%20%231%3F%25.txt")
            require(
                status == 200 and body == b"one\n", "encoded filename contract mismatch"
            )
            for fmt in ("zip", "tar.gz"):
                status, _headers, body = request(f"/foo/archive/foo.{fmt}")
                require(status == 200, f"archive response: {fmt}")
                if fmt == "zip":
                    with zipfile.ZipFile(BytesIO(body)) as archive:
                        data = archive.read("foo/sp ace/f #1?%.txt")
                else:
                    with tarfile.open(fileobj=BytesIO(body), mode="r:gz") as archive:
                        member = archive.extractfile("foo/sp ace/f #1?%.txt")
                        require(member is not None, "missing tar member")
                        data = member.read()
                require(data == b"one\n", f"archive contents: {fmt}")
            status, _headers, pack_list = request("/foo/objects/info/packs")
            require(status == 200, "pack list unavailable")
            pack = pack_list.decode().splitlines()[0][2:]
            status, _headers, full = request(f"/foo/objects/pack/{pack}")
            require(status == 200, "pack unavailable")
            status, headers, body = request(
                f"/foo/objects/pack/{pack}", headers={"Range": "bytes=5-"}
            )
            require(status == 206 and body == full[5:], "actual pack range mismatch")
            require(
                headers["Content-Range"] == f"bytes 5-{len(full) - 1}/{len(full)}",
                "actual pack range headers",
            )
            print(
                "worker-smoke: clone, publisher URLs, safe raw headers, archives and pack range passed",
                flush=True,
            )
            stop()
            write("sp ace/f #1?%.txt", "one\ntwo\n")
            git("add", "-A")
            git("commit", "-qm", "second synthetic publication")
            second = publish()
            require(second["tip"] != first["tip"], "publication did not advance")
            start()
            git("pull", "-q", "--ff-only", cwd=clone)
            require(
                git("rev-parse", "HEAD", cwd=clone) == second["tip"],
                "pull tip mismatch",
            )
            require(
                (clone / "sp ace/f #1?%.txt").read_text() == "one\ntwo\n",
                "pull content mismatch",
            )
            status, _headers, body = request("/foo/raw/sp%20ace/f%20%231%3F%25.txt")
            require(
                status == 200 and body == b"one\ntwo\n", "latest raw content mismatch"
            )
            require(
                len(
                    (out / "smoke/p/foo/git/objects/info/packs")
                    .read_text()
                    .splitlines()
                )
                == 3,
                "second publication did not produce two incremental packs",
            )
            print(
                f"worker-smoke: incremental pull {first['tip'][:12]} -> {second['tip'][:12]} passed",
                flush=True,
            )
            print(
                "worker-smoke: all checks passed (synthetic repositories and local simulated R2 only)",
                flush=True,
            )
        except BaseException:
            if log.exists():
                print(log.read_text(), file=sys.stderr)
            raise
        finally:
            stop()


if __name__ == "__main__":
    main()
