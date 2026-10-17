"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from partlet.manifest import ManifestError, load_manifest
from partlet.publish import publish_all
from partlet.store import LocalStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="partlet")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser(
        "build", help="publish every approved project into a local directory"
    )
    build.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="monorepo checkout (default: current directory)",
    )
    build.add_argument(
        "--manifest", type=Path, help="manifest file (default: <repo>/partlet.toml)"
    )
    build.add_argument("--out", type=Path, required=True, help="output directory")
    return parser


def _build(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    try:
        manifest = load_manifest(args.manifest or repo / "partlet.toml")
    except ManifestError as e:
        print(f"partlet: {e}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="partlet-") as tmp:
        results = publish_all(repo, manifest, LocalStore(args.out), Path(tmp))
    for r in results:
        print(f"{r.name:24} {r.status:10} {(r.tip or '')[:12]:12} {r.reason}")
    return 1 if any(r.status == "failed" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "build":
        return _build(args)
    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    sys.exit(main())
