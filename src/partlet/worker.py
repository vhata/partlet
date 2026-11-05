"""Run the installed Worker with a separate, user-owned deployment config."""

from __future__ import annotations

import datetime
import importlib
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from partlet.manifest import NAME_RE


class WorkerError(Exception):
    """A deployment configuration or local Worker invocation is invalid."""


def _runtime():
    # Other publisher commands do not need the deployment tools.
    return importlib.import_module("partlet.runtime")


_CONFIG_KEYS = {
    "name",
    "account_id",
    "compatibility_date",
    "compatibility_flags",
    "vars",
    "r2_buckets",
    "routes",
    "workers_dev",
    "preview_urls",
}
_WORKER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_BUCKET_NAME = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
_DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


@dataclass(frozen=True)
class WorkerConfig:
    path: Path
    data: dict
    name: str
    source: str
    bucket: str
    domains: tuple[str, ...]


def _keys(data: dict, allowed: set[str], section: str) -> None:
    unexpected = sorted(set(data) - allowed)
    if unexpected:
        raise WorkerError(
            f"unsupported {section} setting(s): {', '.join(unexpected)}; "
            "Partlet supplies its installed Worker and supports only deployment "
            "identity, compatibility settings, SOURCE, BUCKET and custom domains"
        )


def _text(data: dict, key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkerError(f"{section}.{key} must be a nonempty string")
    return value


def _configured(value: str, field: str) -> None:
    if "replace-me" in value:
        raise WorkerError(f"set {field} in your Worker configuration first")


def load_config(path: Path, *, deploy: bool = False) -> WorkerConfig:
    path = path.expanduser().resolve()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkerError(f"cannot read Worker configuration {path}: {exc}") from exc
    _keys(data, _CONFIG_KEYS, "Worker")
    name = _text(data, "name", "Worker")
    if not _WORKER_NAME.fullmatch(name):
        raise WorkerError("Worker.name must be a lowercase Worker name")
    _configured(name, "name")
    date = _text(data, "compatibility_date", "Worker")
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("expected YYYY-MM-DD")
        datetime.date.fromisoformat(date)
    except ValueError as exc:
        raise WorkerError("compatibility_date must be a YYYY-MM-DD date") from exc
    if "account_id" in data and not re.fullmatch(
        r"[a-fA-F0-9]{32}", _text(data, "account_id", "Worker")
    ):
        raise WorkerError("account_id must be a 32-character Cloudflare account ID")
    for key in ("workers_dev", "preview_urls"):
        if key in data and type(data[key]) is not bool:
            raise WorkerError(f"{key} must be a boolean")
    if "compatibility_flags" in data and (
        not isinstance(data["compatibility_flags"], list)
        or any(not isinstance(flag, str) for flag in data["compatibility_flags"])
    ):
        raise WorkerError("compatibility_flags must be an array of strings")
    variables = data.get("vars")
    if not isinstance(variables, dict):
        raise WorkerError("Worker configuration needs [vars] with SOURCE")
    _keys(variables, {"SOURCE"}, "vars")
    source = _text(variables, "SOURCE", "vars")
    if not NAME_RE.fullmatch(source) or source in (".", ".."):
        raise WorkerError(f"vars.SOURCE must match {NAME_RE.pattern}")
    _configured(source, "vars.SOURCE")
    buckets = data.get("r2_buckets")
    if not isinstance(buckets, list) or len(buckets) != 1:
        raise WorkerError("Worker configuration needs exactly one [[r2_buckets]]")
    binding = buckets[0]
    if not isinstance(binding, dict):
        raise WorkerError("r2_buckets must contain a table")
    _keys(binding, {"binding", "bucket_name", "remote"}, "r2_buckets")
    if binding.get("binding") != "BUCKET":
        raise WorkerError("the R2 binding must be named BUCKET")
    if "remote" in binding and binding["remote"] is not False:
        raise WorkerError(
            "remote R2 bindings are unsupported; remove remote or set false"
        )
    bucket = _text(binding, "bucket_name", "r2_buckets")
    if not _BUCKET_NAME.fullmatch(bucket):
        raise WorkerError("r2_buckets.bucket_name must be a lowercase R2 bucket name")
    _configured(bucket, "r2_buckets.bucket_name")
    routes = data.get("routes", [])
    if not isinstance(routes, list):
        raise WorkerError("routes must be an array of custom-domain tables")
    domains = []
    for route in routes:
        if not isinstance(route, dict):
            raise WorkerError("routes must contain tables")
        _keys(route, {"pattern", "custom_domain"}, "routes")
        domain = _text(route, "pattern", "routes")
        if route.get("custom_domain") is not True or not _DOMAIN.fullmatch(domain):
            raise WorkerError("each route must be a hostname with custom_domain = true")
        if deploy:
            _configured(domain, "routes.pattern")
        domains.append(domain)
    if deploy and not domains and data.get("workers_dev") is not True:
        raise WorkerError(
            "deployment needs a custom-domain route or workers_dev = true"
        )
    return WorkerConfig(path, data, name, source, bucket, tuple(domains))


def init_config(
    directory: Path,
    *,
    name: str = "partlet",
    source: str = "replace-me",
    bucket: str = "replace-me",
    domain: str | None = None,
    workers_dev: bool = False,
    account_id: str | None = None,
    announce: bool = True,
) -> Path:
    """Create an editable config without pinning paths to this installation."""
    if workers_dev and domain is not None:
        raise WorkerError("choose either workers.dev or a custom domain")
    directory = directory.expanduser().absolute()
    if directory.is_symlink():
        raise WorkerError("choose a deployment directory that is not a symlink")
    for filename in ("wrangler.toml", ".gitignore"):
        path = directory / filename
        if path.exists() or path.is_symlink():
            raise WorkerError(f"refusing to overwrite {path}; choose another directory")
    runtime = _runtime()
    try:
        template = runtime.asset_root() / "worker" / "wrangler.toml"
    except runtime.SetupError as exc:
        raise WorkerError(str(exc)) from exc
    compatibility = tomllib.loads(template.read_text())["compatibility_date"]
    config = {
        "name": name,
        "compatibility_date": compatibility,
        "workers_dev": workers_dev,
        "preview_urls": False,
    }
    if account_id is not None:
        config["account_id"] = account_id
    config.update(
        vars={"SOURCE": source},
        r2_buckets=[{"binding": "BUCKET", "bucket_name": bucket}],
    )
    if not workers_dev:
        config["routes"] = [
            {"pattern": domain or "partlet.replace-me.example", "custom_domain": True}
        ]
    text = (
        "# Your deployment settings. Partlet supplies the installed Worker code.\n"
        "# Keep this file when upgrading Partlet; do not add a main entry point.\n"
        + tomlkit.dumps(config)
    )
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "wrangler.toml").open("x", encoding="utf-8") as stream:
        stream.write(text)
    with (directory / ".gitignore").open("x", encoding="utf-8") as stream:
        stream.write(".partlet/\n")
    path = directory / "wrangler.toml"
    choices = (
        "SOURCE and bucket_name"
        if workers_dev
        else "SOURCE, bucket_name and your domain"
    )
    if announce:
        print(f"Created {path}. Set {choices} before deploying.")
    return path


def _env(*, local: bool) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("AWS_", "R2_", "PARTLET_R2_", "WRANGLER_"))
        and not (local and key.startswith(("CLOUDFLARE_", "CF_")))
    }
    env.update(
        WRANGLER_SEND_METRICS="false",
        CLOUDFLARE_CF_FETCH_ENABLED="false",
        CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV="false",
        WRANGLER_NO_SKILLS_UPDATE_PROMPTS="true",
    )
    if local:
        env["WRANGLER_HIDE_BANNER"] = "true"
    return env


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> int:
    # A dev server must stop on Ctrl-C or when its parent receives SIGTERM.
    process = subprocess.Popen(command, cwd=cwd, env=env)
    try:
        return process.wait()
    except BaseException:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise


@contextmanager
def _session(config: WorkerConfig, purpose: str):
    state = config.path.parent / ".partlet"
    if state.is_symlink():
        raise WorkerError(f"refusing symlinked state directory {state}")
    state.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{purpose}-", dir=state) as temporary:
        directory = Path(temporary)
        # Never let .env/.dev.vars, a package build or Wrangler's generated
        # config redirect in the user's directory change the chosen operation.
        effective = directory / "wrangler.toml"
        effective.write_text(tomlkit.dumps(config.data), encoding="utf-8")
        yield directory, effective


def run_worker(args, *, confirm: Callable[[str], bool]) -> int:
    if args.worker_command == "init":
        init_config(
            args.directory,
            name=args.name,
            source=args.source,
            bucket=args.bucket,
            domain=args.domain,
            workers_dev=args.workers_dev,
            account_id=args.account_id,
        )
        return 0
    runtime = _runtime()
    try:
        root = runtime.worker_root()
    except runtime.SetupError as exc:
        raise WorkerError(str(exc)) from exc
    wrangler = str(root / "node_modules" / ".bin" / "wrangler")
    if args.worker_command in ("login", "whoami"):
        return _run([wrangler, args.worker_command], cwd=root, env=_env(local=False))

    deploy = args.worker_command == "deploy"
    config = load_config(args.config, deploy=deploy)
    local = not deploy or args.dry_run
    if deploy and not args.dry_run:
        account = config.data.get("account_id", "Wrangler's authenticated account")
        targets = list(config.domains)
        if config.data.get("workers_dev") is True:
            targets.append("this Worker's workers.dev address")
        print(
            f"Billable: deploy Worker {config.name!r}, bound to existing R2 bucket "
            f"{config.bucket!r}, SOURCE {config.source!r}, on "
            f"{', '.join(targets)}, using account {account}."
        )
        if not args.yes and not confirm("Deploy this Worker to Cloudflare? [y/N] "):
            print("Deployment cancelled.")
            return 1
    with _session(config, "deploy" if deploy else "preview") as (session, effective):
        command = [
            wrangler,
            "deploy" if deploy else "dev",
            str(root / "src" / "index.ts"),
            "--config",
            str(effective),
            "--experimental-provision=false",
            "--experimental-auto-create=false",
        ]
        env = _env(local=local)
        if deploy:
            command.append("--autoconfig=false")
            if args.dry_run:
                command += ["--dry-run", "--outdir", str(session / "bundle")]
        else:
            if not 1 <= args.port <= 65535:
                raise WorkerError("preview port must be between 1 and 65535")
            out = args.out.expanduser().resolve()
            if not out.is_dir() or not (out / config.source).is_dir():
                raise WorkerError(
                    f"{out} must contain publisher output for SOURCE {config.source!r}; "
                    "run partlet build --out DIRECTORY --scan first"
                )
            node = shutil.which("node")
            if node is None:
                raise WorkerError(
                    "Node is required; install it, then run partlet setup --worker"
                )
            persistence = session / "r2"
            code = _run(
                [
                    node,
                    str(root / "tools" / "seed-r2.mjs"),
                    str(out),
                    str(persistence),
                    config.bucket,
                ],
                cwd=session,
                env=env,
            )
            if code:
                return code
            command += [
                "--local",
                "--ip",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--inspector-port",
                "0",
                "--persist-to",
                str(persistence),
                "--show-interactive-dev-session=false",
            ]
            print(
                f"Local preview for {config.name}: http://127.0.0.1:{args.port}/",
                flush=True,
            )
        return _run(command, cwd=session, env=env)
