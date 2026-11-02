"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
from pathlib import Path

from partlet.lock import LockError, describe_holder, lock_key, read_lock, store_lock
from partlet.manifest import NAME_RE, Manifest, ManifestError, load_manifest
from partlet.publish import (
    CheckoutError,
    check_checkout,
    project_prefix,
    publish_all,
    unpublish_project,
)
from partlet.scan import Scanner
from partlet.store import LocalStore, R2Config, R2Store, Store, StoreError
from partlet.summary import summary_markdown, write_summary
from partlet.tools import ToolError, check_tools


def _repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="monorepo checkout (default: current directory)",
    )
    parser.add_argument(
        "--manifest", type=Path, help="manifest file (default: <repo>/partlet.toml)"
    )


def _summary_arg(parser: argparse.ArgumentParser) -> None:
    default = os.environ.get("GITHUB_STEP_SUMMARY")
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(default) if default else None,
        help="append a Markdown summary here (default: $GITHUB_STEP_SUMMARY)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="partlet")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build", help="publish every approved project into a local directory"
    )
    _repo_args(build)
    build.add_argument("--out", type=Path, required=True, help="output directory")
    build.add_argument(
        "--scan",
        action="store_true",
        help="scan each export with gitleaks before writing it, as publish does",
    )
    _summary_arg(build)

    publish = sub.add_parser(
        "publish", help="publish every approved project to R2 (the CI entry point)"
    )
    _repo_args(publish)
    _summary_arg(publish)

    unpublish = sub.add_parser(
        "unpublish", help="delete a project's stored objects and update the index"
    )
    unpublish.add_argument("name", help="project name")
    _repo_args(unpublish)
    unpublish.add_argument("--out", type=Path, help="local store instead of R2")
    unpublish.add_argument("--yes", action="store_true", help="do not ask")

    unlock = sub.add_parser("unlock", help="remove a stopped publisher's stale lock")
    _repo_args(unlock)
    unlock.add_argument("--out", type=Path, help="local store instead of R2")
    unlock.add_argument("--yes", action="store_true", help="do not ask")

    return parser


def _error(message: object) -> int:
    print(f"partlet: {message}", file=sys.stderr)
    return 2


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _forget_r2_keys() -> None:
    """Commands that never use R2 still keep its keys from child processes."""
    for name in ("PARTLET_R2_ACCESS_KEY_ID", "PARTLET_R2_SECRET_ACCESS_KEY"):
        os.environ.pop(name, None)


def _manifest_path(args: argparse.Namespace) -> Path:
    return args.manifest or args.repo.resolve() / "partlet.toml"


def _publish_into(
    repo: Path,
    manifest: Manifest,
    store: Store,
    scanner: Scanner | None,
    versions: dict[str, str],
    summary: Path | None,
    title: str,
) -> int:
    try:
        with (
            store_lock(store, manifest.site.source, describe_holder()),
            tempfile.TemporaryDirectory(prefix="partlet-") as tmp,
        ):
            results = publish_all(repo, manifest, store, Path(tmp), scanner)
    except (LockError, StoreError, OSError) as e:
        print(f"partlet: {e}", file=sys.stderr)
        _save_summary(summary, summary_markdown(title, [], versions, error=str(e)))
        return 1
    for r in results:
        print(f"{r.name:24} {r.status:10} {(r.tip or '')[:12]:12} {r.reason}")
    if not _save_summary(summary, summary_markdown(title, results, versions)):
        return 1
    return 1 if any(r.status == "failed" for r in results) else 0


def _save_summary(path: Path | None, text: str) -> bool:
    try:
        write_summary(path, text)
    except OSError as exc:
        print(f"partlet: cannot write summary: {exc}", file=sys.stderr)
        return False
    return True


def _build(args: argparse.Namespace) -> int:
    _forget_r2_keys()
    repo = args.repo.resolve()
    try:
        manifest = load_manifest(_manifest_path(args))
        tools = check_tools(gitleaks=args.scan)
    except (ManifestError, ToolError, OSError, UnicodeError) as e:
        return _error(e)
    scanner = Scanner(tools.gitleaks, repo) if tools.gitleaks else None
    return _publish_into(
        repo,
        manifest,
        LocalStore(args.out),
        scanner,
        tools.versions,
        args.summary,
        "Partlet build",
    )


def _publish(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    manifest_path = _manifest_path(args)
    try:
        # First, so the keys leave the environment before any child process
        # (git, filter-repo, gitleaks) starts.
        config = R2Config.from_env(os.environ)
        manifest = load_manifest(manifest_path)
        check_checkout(
            repo, manifest.site.branch, manifest_path, expected_manifest=manifest
        )
        tools = check_tools(gitleaks=True)
        store = R2Store(config)
    except (
        StoreError,
        ManifestError,
        CheckoutError,
        ToolError,
        OSError,
        UnicodeError,
    ) as e:
        return _error(e)
    return _publish_into(
        repo,
        manifest,
        store,
        Scanner(tools.gitleaks, repo),
        tools.versions,
        args.summary,
        "Partlet publish",
    )


def _store_for(args: argparse.Namespace) -> Store:
    if args.out is not None:
        _forget_r2_keys()
        return LocalStore(args.out)
    return R2Store(R2Config.from_env(os.environ))


def _unpublish(args: argparse.Namespace) -> int:
    name = args.name
    if not NAME_RE.fullmatch(name) or name.endswith(".git"):
        _forget_r2_keys()
        return _error(f"invalid project name {name!r}")
    manifest_path = _manifest_path(args)
    try:
        store = _store_for(args)
        manifest = load_manifest(manifest_path)
    except (StoreError, ManifestError, OSError, UnicodeError) as exc:
        return _error(exc)
    project = manifest.projects.get(name)
    if project is not None and project.approved is not None:
        return _error(
            f"{name} is still approved in {manifest_path}; remove [projects.{name}] "
            "and push that first, or the next publish restores it"
        )
    site = manifest.site
    prefix = f"{project_prefix(site.source, name)}/"
    try:
        with store_lock(store, site.source, describe_holder()):
            keys = store.list(prefix)
            question = f"Delete {len(keys)} keys under {prefix} in {store!r}? [y/N] "
            if not args.yes and not _confirm(question):
                print("partlet: nothing deleted")
                return 1
            removed = unpublish_project(store, site, name)
    except (LockError, StoreError, OSError) as exc:
        print(f"partlet: {exc}", file=sys.stderr)
        return 1
    print(f"partlet: removed {removed} keys under {prefix} and rebuilt the index")
    return 0


def _unlock(args: argparse.Namespace) -> int:
    try:
        store = _store_for(args)
        source = load_manifest(_manifest_path(args)).site.source
    except (StoreError, ManifestError, OSError, UnicodeError) as exc:
        return _error(exc)
    try:
        held = store.get(lock_key(source))
        if held is None:
            print(f"partlet: {source} is not locked")
            return 0
        description = read_lock(store, source) or {}
        print(
            f"partlet: {source} is locked by {description.get('holder')} "
            f"since {description.get('since')}"
        )
        question = "Remove the lock? Only do this if that run is not running. [y/N] "
        if not args.yes and not _confirm(question):
            return 1
        # Human confirmation may take minutes. Never remove a different lock
        # that replaced the one shown before the question. R2 has no atomic
        # compare-and-delete, so the holder must still be verified stopped.
        if store.get(lock_key(source)) != held:
            print(
                "partlet: lock changed; inspect its holder and try again",
                file=sys.stderr,
            )
            return 1
        store.delete(lock_key(source))
    except (StoreError, OSError) as exc:
        print(f"partlet: {exc}", file=sys.stderr)
        return 1
    print("partlet: lock removed")
    return 0


def _exit_on_sigterm(signum, frame):
    # A cancelled CI job gets SIGTERM; exiting this way runs the `finally`
    # blocks, so the lock is released.
    raise SystemExit(128 + signum)


COMMANDS = {
    "build": _build,
    "publish": _publish,
    "unpublish": _unpublish,
    "unlock": _unlock,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    previous = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        command = COMMANDS[args.command]
        return command(args)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
