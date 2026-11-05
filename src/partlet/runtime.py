"""Explicit, per-user installation of Partlet's non-Python tools.

The installed Python package is immutable. Only ``partlet setup`` downloads
tools; ordinary commands look up an already prepared, content-keyed runtime.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from partlet.gitutil import clean_env


class SetupError(Exception):
    """A packaged asset or an explicitly installed tool is unavailable."""


def asset_root() -> Path:
    """Return packaged resources, or their authoritative development sources."""
    package = Path(__file__).resolve().parent
    bundled = package / "_assets"
    if bundled.is_dir():
        return bundled
    checkout = package.parent.parent
    if (checkout / "worker" / "package-lock.json").is_file() and (
        checkout / "scripts" / "install-gitleaks.sh"
    ).is_file():
        return checkout
    raise SetupError("Partlet's tool assets are missing; reinstall Partlet")


def data_root() -> Path:
    """Per-user application data; never the source repo or package directory."""
    override = os.environ.get("PARTLET_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg).expanduser().resolve() / "partlet"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "partlet"
    return Path.home() / ".local" / "share" / "partlet"


def managed_gitleaks() -> Path:
    from partlet.scan import GITLEAKS_VERSION

    return data_root() / "tools" / f"gitleaks-{GITLEAKS_VERSION}" / "gitleaks"


def _worker_files() -> list[Path]:
    root = asset_root() / "worker"
    files = [
        root / "package.json",
        root / "package-lock.json",
        root / ".node-version",
        root / "wrangler.toml",
        root / "tools" / "seed-r2.mjs",
        *sorted((root / "src").rglob("*.ts")),
    ]
    if not (root / "src" / "index.ts").is_file() or any(
        not file.is_file() for file in files
    ):
        raise SetupError("Partlet's Worker assets are incomplete; reinstall Partlet")
    return files


def _worker_destination() -> Path:
    digest = hashlib.sha256()
    root = asset_root() / "worker"
    for file in _worker_files():
        name = file.relative_to(root).as_posix().encode()
        content = file.read_bytes()
        # Lengths keep filenames and contents unambiguous even with odd bytes.
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    digest.update(f"{platform.system()}-{platform.machine()}".encode())
    return data_root() / "workers" / digest.hexdigest()


def _ready(root: Path) -> bool:
    return (root / ".complete").is_file() and (
        root / "node_modules" / ".bin" / "wrangler"
    ).is_file()


def worker_root() -> Path:
    root = _worker_destination()
    if not _ready(root):
        raise SetupError("Worker tools are not installed; run `partlet setup --worker`")
    return root


def _setup_env() -> dict[str, str]:
    """Downloads/install scripts get no publisher or cloud credentials."""
    prefixes = (
        "AWS_",
        "R2_",
        "PARTLET_R2_",
        "CLOUDFLARE_",
        "CF_",
        "WRANGLER_",
        "GITLEAKS_",
        "NPM_CONFIG_",
    )
    env = {
        key: value
        for key, value in clean_env().items()
        if not key.upper().startswith(prefixes)
        and key not in ("NODE_OPTIONS", "NODE_PATH", "NODE_ENV", "BASH_ENV", "ENV")
    }
    env.update(
        WRANGLER_SEND_METRICS="false",
        CLOUDFLARE_CF_FETCH_ENABLED="false",
        npm_config_userconfig=os.devnull,
        # npm refuses to load the same path for both user and global config.
        npm_config_globalconfig=str(data_root() / "npm-globalrc"),
        npm_config_cache=str(data_root() / "npm-cache"),
    )
    return env


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, check=False)
    except OSError as exc:
        raise SetupError(f"cannot run {command[0]}: {exc}") from exc
    if result.returncode:
        raise SetupError(
            f"{Path(command[0]).name} failed ({result.returncode}); "
            "fix the reported error and rerun `partlet setup`"
        )


def _node_tools(env: dict[str, str], cwd: Path) -> str:
    pin = (asset_root() / "worker" / ".node-version").read_text().strip()
    required_major = int(pin.split(".")[0])
    versions = {}
    for command in ("node", "npm"):
        executable = shutil.which(command)
        if executable is None:
            raise SetupError(
                f"{command} is required for Worker setup; install Node {pin} "
                "and npm >=11.19, then rerun `partlet setup --worker`"
            )
        try:
            result = subprocess.run(
                [executable, "--version"],
                cwd=cwd,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise SetupError(f"cannot check {command}: {exc}") from exc
        match = re.fullmatch(
            r"v?(\d+)\.(\d+)(?:\.\d+)?(?:[-+][\w.-]+)?", result.stdout.strip()
        )
        if result.returncode or match is None:
            raise SetupError(
                f"cannot determine {command} version; check its installation"
            )
        versions[command] = tuple(int(part) for part in match.groups())
    if versions["node"][0] < required_major:
        raise SetupError(
            f"Node {pin} or newer is required; rerun `partlet setup --worker` after upgrading"
        )
    if versions["npm"] < (11, 19):
        raise SetupError(
            "npm >=11.19 is required to enforce the install-script allowlist"
        )
    if versions["node"][0] != required_major:
        print(
            f"setup: Node {pin} is pinned; using newer Node {versions['node'][0]}",
            flush=True,
        )
    return shutil.which("npm")  # checked above


def _install_scanner(root: Path, env: dict[str, str]) -> None:
    from partlet.scan import ScanError, check_gitleaks

    destination = managed_gitleaks()
    if destination.is_file():
        try:
            check_gitleaks(str(destination), env=env)
            print(
                f"setup: pinned secret scanner ready in {destination.parent}",
                flush=True,
            )
            return
        except ScanError:
            pass
    destination.parent.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".scanner-", dir=destination.parent.parent
    ) as temp:
        stage = Path(temp) / "bin"
        print("setup: downloading and verifying the pinned secret scanner", flush=True)
        _run(
            ["bash", str(asset_root() / "scripts" / "install-gitleaks.sh"), str(stage)],
            cwd=root,
            env=env,
        )
        try:
            check_gitleaks(str(stage / "gitleaks"), env=env)
        except ScanError as exc:
            raise SetupError(str(exc)) from exc
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage / "gitleaks", destination)


def _install_worker(root: Path, env: dict[str, str]) -> None:
    destination = _worker_destination()
    if _ready(destination):
        print(f"setup: Worker tools ready in {destination}", flush=True)
        return
    npm = _node_tools(env, root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".worker-", dir=destination.parent) as temp:
        stage = Path(temp) / "worker"
        stage.mkdir()
        for file in _worker_files():
            target = stage / file.relative_to(asset_root() / "worker")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
        print("setup: installing pinned Worker dependencies with npm ci", flush=True)
        _run(
            [
                npm,
                "ci",
                "--include=dev",
                "--no-audit",
                "--no-fund",
                "--registry=https://registry.npmjs.org",
            ],
            cwd=stage,
            env=env,
        )
        if not (stage / "node_modules" / ".bin" / "wrangler").is_file():
            raise SetupError(
                "npm did not install Wrangler; rerun `partlet setup --worker`"
            )
        (stage / ".complete").touch()
        if destination.exists():
            shutil.rmtree(destination)
        stage.rename(destination)
    print(f"setup: Worker tools ready in {destination}", flush=True)


def setup(*, worker: bool = False) -> None:
    """Download pinned tools only when explicitly requested by the user."""
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    env = _setup_env()
    # Serialise publication of prepared directories, including scanner repair.
    # A process interrupted during downloads leaves no completed runtime.
    with (root / ".setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            (root / "npm-globalrc").write_text("")
            _install_scanner(root, env)
            if worker:
                _install_worker(root, env)
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(lock, fcntl.LOCK_UN)
