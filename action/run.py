"""Load only the action's Partlet checkout, even inside a private source tree."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# -I isolates this interpreter. Also isolate Python children (filter-repo)
# without making the private checkout available through inherited variables.
for _name in tuple(os.environ):
    if _name.startswith("PYTHON"):
        os.environ.pop(_name)
os.environ["PYTHONSAFEPATH"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from partlet.cli import main
from partlet.gitutil import GitError, git, git_out
from partlet.manifest import ManifestError, load_manifest
from partlet.publish import CheckoutError, check_checkout
from partlet.site.themes import ThemeError, resolve_theme


def prepare() -> None:
    repo = Path.cwd()
    path = repo / os.environ.get("MANIFEST", "partlet.toml")
    manifest = load_manifest(path)
    branch = manifest.site.branch
    git("check-ref-format", f"refs/heads/{branch}", cwd=repo)
    if branch.startswith("-"):
        raise CheckoutError("publishing branch must not start with '-'")
    if git_out("rev-parse", "--is-shallow-repository", cwd=repo) != "false":
        raise CheckoutError("publishing needs full history; use fetch-depth: 0")
    ref = f"refs/heads/{branch}"
    try:
        git_out("rev-parse", "--verify", f"{ref}^{{commit}}", cwd=repo)
    except GitError:
        try:
            remote = git_out(
                "rev-parse",
                "--verify",
                f"refs/remotes/origin/{branch}^{{commit}}",
                cwd=repo,
            )
        except GitError:
            raise CheckoutError(
                f"neither {ref} nor origin/{branch} exists; use fetch-depth: 0"
            ) from None
        # Atomic create; never overwrite a publishing branch that already exists.
        git("update-ref", ref, remote, "", cwd=repo)
    check_checkout(repo, branch, path, expected_manifest=manifest)
    resolve_theme(
        manifest.site.theme,
        repo,
        branch=branch,
        manifest_path=path,
        require_clean=True,
    )


def run() -> int:
    try:
        operation = sys.argv[1]
        if operation == "prepare":
            prepare()
            return 0
        if operation != "publish":
            raise ValueError("expected prepare or publish")
        manifest = os.environ.get("MANIFEST", "partlet.toml")
        local = os.environ.get("LOCAL_OUT", "")
        if local:
            # Preview mode exercises the same checkout/committed approval gate.
            for key in ("PARTLET_R2_ACCESS_KEY_ID", "PARTLET_R2_SECRET_ACCESS_KEY"):
                os.environ.pop(key, None)
            prepare()
            return main(
                ["build", "--scan", "--manifest", manifest, "--out", local],
                require_committed=True,
            )
        return main(["publish", "--manifest", manifest])
    except (
        CheckoutError,
        GitError,
        ManifestError,
        ThemeError,
        OSError,
        ValueError,
    ) as exc:
        print(f"partlet action: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
