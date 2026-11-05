"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import pydoc
import signal
import sys
import tempfile
from pathlib import Path

from partlet import __version__
from partlet.export import ExportError
from partlet.gitutil import GitError
from partlet.lock import LockError, describe_holder, lock_key, read_lock, store_lock
from partlet.manifest import (
    NAME_RE,
    SHA_RE,
    Manifest,
    ManifestError,
    load_manifest,
    parse_manifest,
)
from partlet.publish import (
    CheckoutError,
    check_checkout,
    project_prefix,
    publish_all,
    unpublish_project,
)
from partlet.review import ReviewError, fetch_published_tip, run_review
from partlet.scan import ScanError, Scanner
from partlet.site.themes import BUILTIN_THEMES, ResolvedTheme, ThemeError, resolve_theme
from partlet.store import LocalStore, R2Config, R2Store, Store, StoreError
from partlet.summary import summary_markdown, write_summary
from partlet.tools import ToolError, check_tools


def _repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--repo",
        type=Path,
        metavar="DIR",
        default=Path.cwd(),
        help="source checkout (default: current directory)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        metavar="FILE",
        help="manifest file (default: <repo>/partlet.toml)",
    )


def _summary_arg(parser: argparse.ArgumentParser) -> None:
    default = os.environ.get("GITHUB_STEP_SUMMARY")
    parser.add_argument(
        "--summary",
        type=Path,
        metavar="FILE",
        default=Path(default) if default else None,
        help="append a Markdown summary (default: $GITHUB_STEP_SUMMARY)",
    )


class _HelpFormatter(argparse.HelpFormatter):
    """Wrap prose while preserving the layout of command examples."""

    def _fill_text(self, text, width, indent):
        if "\n" in text:
            return argparse.RawDescriptionHelpFormatter._fill_text(
                self, text, width, indent
            )
        return super()._fill_text(text, width, indent)


def _command(sub, name, summary, description, examples):
    return sub.add_parser(
        name,
        help=summary,
        description=description,
        epilog=f"Examples:\n{examples}",
        formatter_class=_HelpFormatter,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="partlet",
        description=(
            "Publish projects from a private Git repository as public, read-only "
            "repositories and a browsable website."
        ),
        epilog=(
            "Start in your source repository, with projects in partlet.toml:\n"
            "  partlet review foo --first-publish       # inspect and approve history\n"
            "  partlet build --scan --out ./preview     # build approved projects locally\n"
            "\n"
            "After hosting setup, commit the approval and push to publish through\n"
            "your GitHub Action. Later fast-forward changes publish automatically.\n"
            "\n"
            "Run 'partlet worker' for local preview and hosting commands.\n"
            "Use 'partlet COMMAND --help' for options and examples.\n"
            "Hosting setup: https://github.com/vhata/partlet/blob/main/docs/GETTING_STARTED.md"
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"partlet {__version__}")
    sub = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    review = _command(
        sub,
        "review",
        "inspect and approve a project's exported history",
        "Inspect a project's full exported history and scan it for secrets. "
        "After your confirmation, write its approval to partlet.toml. "
        "Nothing is uploaded. By default, compare with the public site's tip; "
        "use --first-publish only when the project has never been published.",
        "  partlet review foo --first-publish\n"
        "  partlet review foo\n"
        "  partlet review foo --repo /path/to/source",
    )
    review.add_argument("name", metavar="PROJECT", help="project name in partlet.toml")
    _repo_args(review)
    review.add_argument(
        "--allow-rewrite",
        action="store_true",
        help="authorize replacing the exact published tip after review",
    )
    published_tip = review.add_mutually_exclusive_group()
    published_tip.add_argument(
        "--first-publish",
        action="store_const",
        dest="published_tip",
        const="none",
        help="review a never-published project without contacting the public site",
    )
    published_tip.add_argument(
        "--published-tip",
        metavar="SHA|none",
        help="override the public tip with a full commit hash or 'none'",
    )

    build = _command(
        sub,
        "build",
        "build all approved projects into a local store",
        "Export every approved project into a local object store. Unapproved "
        "projects are skipped. Output is for 'partlet worker preview', "
        "not a directory to open directly in a browser. Nothing is uploaded.",
        "  partlet build --scan --out ./preview\n"
        "  partlet build --scan --out ./preview --repo /path/to/source",
    )
    _repo_args(build)
    build.add_argument(
        "--out", type=Path, metavar="DIR", required=True, help="local output store"
    )
    build.add_argument(
        "--scan",
        action="store_true",
        help="scan each export with gitleaks before writing it, as publish does",
    )
    _summary_arg(build)

    publish = _command(
        sub,
        "publish",
        "publish all approved projects to R2 (used by CI)",
        "Scan and publish every approved project to Cloudflare R2. Requires "
        "PARTLET_R2_* credentials, HEAD at the publishing branch tip, and a "
        "committed manifest. Normally run by your GitHub Action after a push.",
        "  partlet publish\n"
        "  partlet publish --repo /path/to/source --summary ./summary.md",
    )
    _repo_args(publish)
    _summary_arg(publish)

    theme = _command(
        sub,
        "theme",
        "choose and validate site presentation",
        "Choose a bundled theme or a reviewed vendored theme in partlet.toml. "
        "List available themes or validate the configured theme locally; "
        "nothing is uploaded and no cloud credentials are needed.",
        "  partlet theme list\n"
        "  partlet theme check --repo /path/to/source\n"
        "\nUse 'partlet theme COMMAND --help' for options and examples.",
    )
    theme_sub = theme.add_subparsers(
        dest="theme_command", title="commands", metavar="COMMAND", required=True
    )
    _command(
        theme_sub,
        "list",
        "list bundled site themes and supported modes",
        "List the bundled Classic, Paper and Terminal themes and their "
        "automatic, light and dark modes. No source checkout is required.",
        "  partlet theme list",
    )
    theme_check = _command(
        theme_sub,
        "check",
        "validate the configured theme without publishing",
        "Validate the theme selected in partlet.toml and report its content "
        "fingerprint. Vendored files are read from the configured publishing "
        "branch's committed snapshot; local theme edits are not included.",
        "  partlet theme check\n  partlet theme check --repo /path/to/source",
    )
    _repo_args(theme_check)

    worker = _command(
        sub,
        "worker",
        "configure, preview and deploy the public site",
        "Manage the public Cloudflare Worker using a deployment configuration "
        "you own. Preview uses local simulated R2; deployment changes your "
        "Cloudflare account and is billable.",
        "  partlet worker init ./site --source my-monorepo --bucket public-code --workers-dev\n"
        "  partlet worker preview --config ./site/wrangler.toml --out ./preview\n"
        "  partlet worker deploy --config ./site/wrangler.toml --dry-run\n"
        "\nUse 'partlet worker COMMAND --help' for options and examples.",
    )
    worker.set_defaults(command_help=worker)
    worker_sub = worker.add_subparsers(
        dest="worker_command", title="commands", metavar="COMMAND"
    )
    init = _command(
        worker_sub,
        "init",
        "create a deployment configuration",
        "Write wrangler.toml and a .gitignore in DIR without creating cloud "
        "resources. Existing configurations are never replaced. SOURCE must "
        "match site.source in your source repository's partlet.toml.",
        "  partlet worker init ./site --source my-monorepo --bucket public-code --workers-dev\n"
        "  partlet worker init ./site --source my-monorepo --bucket public-code --domain code.example.com",
    )
    init.add_argument(
        "directory", type=Path, metavar="DIR", help="deployment directory"
    )
    init.add_argument(
        "--name",
        metavar="NAME",
        default="partlet",
        help="Worker name (default: partlet)",
    )
    init.add_argument(
        "--source", metavar="SOURCE", default="replace-me", help="manifest site.source"
    )
    init.add_argument(
        "--bucket",
        metavar="BUCKET",
        default="replace-me",
        help="existing R2 bucket name",
    )
    address = init.add_mutually_exclusive_group()
    address.add_argument("--domain", metavar="HOST", help="custom domain")
    address.add_argument(
        "--workers-dev",
        action="store_true",
        help="use Cloudflare's workers.dev address",
    )
    init.add_argument("--account-id", metavar="ID", help="Cloudflare account ID")
    _command(
        worker_sub,
        "login",
        "log in to Cloudflare",
        "Open Wrangler's browser login to authorize Worker management. "
        "Publisher R2 credentials are configured separately.",
        "  partlet worker login",
    )
    _command(
        worker_sub,
        "whoami",
        "show the authenticated Cloudflare account",
        "Show the Cloudflare account currently authenticated with Wrangler.",
        "  partlet worker whoami",
    )
    preview = _command(
        worker_sub,
        "preview",
        "serve a build locally with simulated R2",
        "Seed local simulated R2 from 'partlet build' output and serve the "
        "public site at localhost. The deployment SOURCE must match the build. "
        "No cloud resources are created. Stop the server with Ctrl-C.",
        "  partlet build --scan --out ./preview\n"
        "  partlet worker preview --config ./site/wrangler.toml --out ./preview",
    )
    preview.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        required=True,
        help="deployment wrangler.toml",
    )
    preview.add_argument(
        "--out",
        type=Path,
        metavar="DIR",
        required=True,
        help="partlet build output store",
    )
    preview.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        default=8787,
        help="localhost port (default: 8787)",
    )
    deploy = _command(
        worker_sub,
        "deploy",
        "deploy the configured Worker to Cloudflare",
        "Deploy the installed Worker using your wrangler.toml. Deployment "
        "is billable and requires confirmation. Use --dry-run to validate "
        "and bundle locally without deploying.",
        "  partlet worker deploy --config ./site/wrangler.toml --dry-run\n"
        "  partlet worker deploy --config ./site/wrangler.toml",
    )
    deploy.add_argument(
        "--config",
        type=Path,
        metavar="FILE",
        required=True,
        help="deployment wrangler.toml",
    )
    deploy.add_argument(
        "--dry-run", action="store_true", help="bundle locally without deploying"
    )
    deploy.add_argument(
        "--yes", action="store_true", help="confirm the billable deployment"
    )

    setup = _command(
        sub,
        "setup",
        "install pinned external tools",
        "Download and install the pinned secret scanner into Partlet's "
        "user-data directory. Add --worker to also install the Worker tools "
        "(requires Node/npm). Normal commands never download missing tools.",
        "  partlet setup\n  partlet setup --worker",
    )
    setup.add_argument(
        "--worker", action="store_true", help="also install the Worker deployment tools"
    )

    unpublish = _command(
        sub,
        "unpublish",
        "delete a project's public copy",
        "Delete a project's stored objects and rebuild the site index. First "
        "remove its manifest entry and push that change so the next publish "
        "does not restore it. Uses R2 by default; --out selects a local store.",
        "  partlet unpublish foo\n  partlet unpublish foo --out ./preview",
    )
    unpublish.add_argument("name", metavar="PROJECT", help="public project name")
    _repo_args(unpublish)
    unpublish.add_argument(
        "--out", type=Path, metavar="DIR", help="local store instead of R2"
    )
    unpublish.add_argument(
        "--yes", action="store_true", help="confirm deletion without prompting"
    )

    unlock = _command(
        sub,
        "unlock",
        "remove a stopped publisher's stale lock",
        "Inspect and remove a source's publishing lock after verifying the "
        "holder has stopped. Removing an active publisher's lock permits "
        "overlapping writes. Uses R2 by default; --out selects a local store.",
        "  partlet unlock\n  partlet unlock --out ./preview",
    )
    _repo_args(unlock)
    unlock.add_argument(
        "--out", type=Path, metavar="DIR", help="local store instead of R2"
    )
    unlock.add_argument(
        "--yes", action="store_true", help="confirm removal without prompting"
    )

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
    theme: ResolvedTheme,
) -> int:
    try:
        with (
            store_lock(store, manifest.site.source, describe_holder()),
            tempfile.TemporaryDirectory(prefix="partlet-") as tmp,
        ):
            results = publish_all(
                repo, manifest, store, Path(tmp), scanner, theme=theme
            )
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
        manifest_path = _manifest_path(args)
        manifest = load_manifest(manifest_path)
        theme = resolve_theme(
            manifest.site.theme,
            repo,
            branch=manifest.site.branch,
            manifest_path=manifest_path,
        )
        tools = check_tools(gitleaks=args.scan)
    except (ManifestError, ThemeError, ToolError, OSError, UnicodeError) as e:
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
        theme,
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
        theme = resolve_theme(
            manifest.site.theme,
            repo,
            branch=manifest.site.branch,
            manifest_path=manifest_path,
            require_clean=True,
        )
        tools = check_tools(gitleaks=True)
        store = R2Store(config)
    except (
        StoreError,
        ManifestError,
        CheckoutError,
        ThemeError,
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
        theme,
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


def _review(args: argparse.Namespace) -> int:
    _forget_r2_keys()
    repo = args.repo.resolve()
    manifest_path = _manifest_path(args)
    try:
        original = manifest_path.read_bytes().decode("utf-8")
        manifest = parse_manifest(original)
        if args.name not in manifest.projects:
            return _error(f"no project {args.name!r} in {manifest_path}")
        tools = check_tools(gitleaks=True)
        if args.published_tip == "none":
            published = None
        elif args.published_tip is not None:
            if not SHA_RE.fullmatch(args.published_tip):
                return _error("--published-tip takes a full commit hash or 'none'")
            published = args.published_tip
        else:
            published = fetch_published_tip(manifest.site.base_url, args.name)
        with tempfile.TemporaryDirectory(prefix="partlet-review-") as tmp:
            return run_review(
                repo,
                manifest_path,
                args.name,
                Path(tmp),
                scanner=Scanner(tools.gitleaks, repo),
                published_tip=published,
                allow_rewrite=args.allow_rewrite,
                confirm=_confirm,
                pager=pydoc.pager,
                expected_text=original,
            )
    except (
        ManifestError,
        ToolError,
        ReviewError,
        ExportError,
        GitError,
        ScanError,
        OSError,
        UnicodeError,
    ) as exc:
        return _error(exc)


def _exit_on_sigterm(signum, frame):
    # A cancelled CI job gets SIGTERM; exiting this way runs the `finally`
    # blocks, so the lock is released.
    raise SystemExit(128 + signum)


def _setup(args: argparse.Namespace) -> int:
    from partlet import runtime

    try:
        runtime.setup(worker=args.worker)
        return 0
    except (runtime.SetupError, OSError) as exc:
        return _error(exc)


def _worker(args: argparse.Namespace) -> int:
    from partlet.worker import WorkerError, run_worker

    try:
        return run_worker(args, confirm=_confirm)
    except KeyboardInterrupt:
        print("Worker command stopped.", file=sys.stderr)
        return 130
    except (WorkerError, OSError, UnicodeError) as exc:
        return _error(exc)


def _theme(args: argparse.Namespace) -> int:
    _forget_r2_keys()
    if args.theme_command == "list":
        for name, description in BUILTIN_THEMES.items():
            print(f"{name:12} {description}")
        print("Modes: auto (browser preference), light, dark")
        return 0
    repo = args.repo.resolve()
    manifest_path = _manifest_path(args)
    try:
        manifest = load_manifest(manifest_path)
        theme = resolve_theme(
            manifest.site.theme,
            repo,
            branch=manifest.site.branch,
            manifest_path=manifest_path,
        )
    except (ManifestError, ThemeError, OSError, UnicodeError) as exc:
        return _error(exc)
    print(f"Theme: {theme.name}; mode: {theme.mode}")
    print(f"Fingerprint: {theme.digest}")
    if manifest.site.theme.path is not None:
        print(
            f"Theme files: committed snapshot of refs/heads/{manifest.site.branch}; "
            "local file edits are not included"
        )
    else:
        print("Theme files: bundled with this Partlet installation")
    print(f"Public resources: {len(theme.resources)}")
    return 0


COMMANDS = {
    "setup": _setup,
    "worker": _worker,
    "theme": _theme,
    "build": _build,
    "publish": _publish,
    "unpublish": _unpublish,
    "unlock": _unlock,
    "review": _review,
}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "worker" and args.worker_command is None:
        args.command_help.print_help()
        return 0
    previous = signal.signal(signal.SIGTERM, _exit_on_sigterm)
    try:
        command = COMMANDS[args.command]
        return command(args)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
