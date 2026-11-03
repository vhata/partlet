"""Publish every approved project from a monorepo into a Store."""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from partlet import __version__
from partlet.archive import ARCHIVE_FORMATS, make_archives
from partlet.export import ExportError, export_project
from partlet.gitstatic import PACK_EXTS, read_state, upload_pack, write_pointers
from partlet.gitutil import GitError, git, git_out
from partlet.history import HistoryError, check_history
from partlet.manifest import NAME_RE, Manifest, Project, Site, parse_manifest
from partlet.scan import ScanError, Scanner
from partlet.site.render import (
    ProjectInfo,
    render_project,
    render_site_index,
    site_stylesheet,
)
from partlet.site.tree import TreeError, read_tree
from partlet.store import LocalPathError, LocalStore, Store, StoreError

# Changing stored page keys must rebuild even when the package version and
# repository tip are unchanged, and must leave earlier builds immutable.
SITE_LAYOUT = "directory-children-v1"

# Mutable Git metadata now uses no-store. Legacy metadata may remain fresh
# for 60 seconds; reserve the rest of an hour for an in-flight fetch. The
# clock starts only when a sweep observes the pack unreferenced.
PACK_RETENTION_SECONDS = 3600


def _pack_retirements(store: Store, prefix: str) -> dict[str, float]:
    raw = store.get(f"{prefix}/retired-packs.json")
    try:
        retired = {} if raw is None else json.loads(raw)
        if not isinstance(retired, dict) or any(
            not isinstance(name, str)
            or isinstance(since, bool)
            or not isinstance(since, (int, float))
            or not math.isfinite(since)
            or since < 0
            for name, since in retired.items()
        ):
            raise ValueError("invalid retirement times")
    except (ValueError, TypeError, UnicodeError, OverflowError) as exc:
        raise StoreError("invalid pack retirement state; no packs deleted") from exc
    return retired


def _revive_packs(store: Store, prefix: str, packs: tuple[str, ...]) -> None:
    """Clear old timers durably before a pointer advertises these packs.

    A failure after advertisement must not leave an old, expired retirement
    timestamp on a revived pack, even if several subsequent sweeps fail.
    """
    retired = _pack_retirements(store, prefix)
    keys = {f"{prefix}/git/objects/pack/{p}.{ext}" for p in packs for ext in PACK_EXTS}
    pending = {name: since for name, since in retired.items() if name not in keys}
    if pending != retired:
        _put_json(store, f"{prefix}/retired-packs.json", pending)


def _sweep_packs(store: Store, prefix: str, keep: set[str]) -> None:
    """Persist retirement times before deleting any expired pack objects.

    Keeping this outside `current` survives interrupted pointer updates and
    unchanged retries. Unknown uploads receive the same conservative grace.
    """
    retired = _pack_retirements(store, prefix)
    now = time.time()
    if not math.isfinite(now) or now < 0:
        raise StoreError("invalid clock; no packs deleted")
    candidates = set(store.list(f"{prefix}/git/objects/pack/")) - keep
    pending = {name: retired.get(name, now) for name in sorted(candidates)}
    if pending != retired:
        _put_json(store, f"{prefix}/retired-packs.json", pending)
    for name, since in pending.items():
        if now - since >= PACK_RETENTION_SECONDS:
            store.delete(name)


@dataclass(frozen=True)
class ProjectResult:
    name: str
    status: Literal["published", "unchanged", "skipped", "failed"]
    tip: str | None = None
    reason: str = ""


def project_prefix(source: str, name: str) -> str:
    return f"{source}/p/{name}"


def build_id(tip: str, description: str, base_url: str) -> str:
    digest = hashlib.sha256(
        f"{tip}\0{description}\0{base_url}\0{__version__}\0{SITE_LAYOUT}".encode()
    )
    return digest.hexdigest()[:16]


def _read_json(store: Store, key: str):
    raw = store.get(key)
    return None if raw is None else json.loads(raw)


def _put_json(store: Store, key: str, value) -> None:
    store.put(
        key,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "application/json",
    )


def _sweep(store: Store, prefix: str) -> None:
    """Retire packs by age; sweep unreferenced site builds and archives.

    Kept: the packs `objects/info/packs` lists, the build and archives
    `current` names, and what was live before the publish that wrote
    `current`, which it records as `previous`; that is the one publish of grace
    for superseded keys. Unreferenced packs additionally get at least an
    hour from their first observed retirement, including orphaned uploads.
    """
    current = _read_json(store, f"{prefix}/current") or {}
    previous = current.get("previous") or {}
    packs = {*read_state(store, f"{prefix}/git").packs, *previous.get("packs", ())}
    keep = {f"{prefix}/git/objects/pack/{p}.{ext}" for p in packs for ext in PACK_EXTS}
    builds: list[str] = []
    for gen in (current, previous):
        if gen.get("build"):
            builds.append(f"{prefix}/site/{gen['build']}/")
        if gen.get("tip"):
            keep |= {f"{prefix}/archive/{gen['tip']}.{f}" for f in ARCHIVE_FORMATS}
    _sweep_packs(store, prefix, keep)
    for area in ("site/", "archive/"):
        for key in store.list(f"{prefix}/{area}"):
            if key not in keep and not key.startswith(tuple(builds)):
                store.delete(key)
    # Superseded-key list written before 2026-10-17; nothing reads it now.
    store.delete(f"{prefix}/cleanup.json")


def publish_project(
    monorepo: Path,
    manifest: Manifest,
    project: Project,
    store: Store,
    workdir: Path,
    scanner: Scanner | None = None,
) -> ProjectResult:
    if project.approved is None:
        return ProjectResult(project.name, "skipped", reason="not approved")
    site = manifest.site
    prefix = project_prefix(site.source, project.name)
    pdir = workdir / project.name
    tip = None
    try:
        mailmap = monorepo / site.mailmap if site.mailmap else None
        repo = pdir / "export.git"
        tip = export_project(monorepo, site.branch, project, repo, mailmap)

        state = read_state(store, f"{prefix}/git")
        decision = check_history(
            repo, tip, state.tip, project.approved, project.allow_rewrite_of
        )
        current = _read_json(store, f"{prefix}/current")
        build = build_id(tip, project.description, site.base_url)
        # Validate paths even for an existing build produced by an older
        # publisher, and before any uploads or pointer changes.
        entries = read_tree(repo, tip)
        updated = git_out("show", "-s", "--format=%cI", tip, cwd=repo)
        info = ProjectInfo(
            project.name, project.description, tip, site.base_url, updated
        )
        rendered = render_project(info, entries)
        if isinstance(store, LocalStore):
            store.validate_keys(f"{prefix}/site/{build}/{key}" for key in rendered)
        if decision.action == "unchanged" and current and current.get("build") == build:
            _sweep(store, prefix)
            return ProjectResult(project.name, "unchanged", tip, decision.reason)

        # Scan all exported history before the first project write, including
        # re-renders. Path validation above also remains before any uploads.
        if scanner is not None:
            findings = scanner.scan(repo, pdir / "scan")
            if findings:
                shown = "; ".join(f.describe() for f in findings[:5])
                more = f" and {len(findings) - 5} more" if len(findings) > 5 else ""
                return ProjectResult(
                    project.name,
                    "failed",
                    tip,
                    f"secret scan: {len(findings)} finding(s): {shown}{more}. "
                    "Run partlet review to see them; accept a false positive in "
                    ".gitleaks.toml or .gitleaksignore",
                )

        # 1. New objects first: nothing references them yet.
        plan = None
        if decision.action != "unchanged":
            plan = upload_pack(
                store,
                f"{prefix}/git",
                repo,
                tip,
                state,
                pdir / "packs",
                full=decision.action == "rewrite",
            )

        for key, data in rendered.items():
            store.put(f"{prefix}/site/{build}/{key}", data)
        for fmt, data in make_archives(repo, project.name, tip).items():
            store.put(f"{prefix}/archive/{tip}.{fmt}", data)

        # 2. Pointers, so refs never name objects that are not uploaded yet.
        if plan is not None:
            _revive_packs(store, prefix, plan.packs)
            write_pointers(store, f"{prefix}/git", plan, state)
        _put_json(
            store,
            f"{prefix}/current",
            {
                "name": project.name,
                "description": project.description,
                "tip": tip,
                "build": build,
                "updated": updated,
                # What was live until now, kept for one publish of grace.
                "previous": {
                    "build": (current or {}).get("build"),
                    "tip": (current or {}).get("tip"),
                    "packs": list(state.packs),
                },
            },
        )

        # 3. Delete what the publish before this one superseded, and anything
        # an interrupted publish left behind.
        _sweep(store, prefix)
        reason = "re-rendered" if decision.action == "unchanged" else decision.reason
        return ProjectResult(project.name, "published", tip, reason)
    except (
        ExportError,
        HistoryError,
        GitError,
        TreeError,
        LocalPathError,
        ScanError,
    ) as e:
        return ProjectResult(project.name, "failed", tip, str(e))


class CheckoutError(Exception):
    """The source checkout does not match the publishing branch and manifest."""


def check_checkout(
    repo: Path,
    branch: str,
    manifest_path: Path,
    *,
    expected_manifest: Manifest | None = None,
) -> None:
    """Require HEAD at the publishing tip and the manifest exactly as committed."""
    try:
        head = git_out("rev-parse", "--verify", "HEAD^{commit}", cwd=repo)
        toplevel = Path(git_out("rev-parse", "--show-toplevel", cwd=repo))
    except GitError as exc:
        raise CheckoutError(f"{repo} is not a git checkout: {exc}") from exc
    try:
        tip = git_out(
            "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo
        )
    except GitError:
        raise CheckoutError(
            f"branch {branch!r} not found in {repo}: publishing needs a local "
            f"refs/heads/{branch}"
        ) from None
    if head != tip:
        raise CheckoutError(
            f"HEAD is {head[:12]} but {branch} is at {tip[:12]}; partlet publish "
            f"runs from a checkout of the tip of {branch}"
        )
    try:
        relative = manifest_path.resolve().relative_to(toplevel.resolve())
    except ValueError:
        raise CheckoutError(f"{manifest_path} is not inside {toplevel}") from None
    try:
        committed = git("show", f"{tip}:{relative.as_posix()}", cwd=repo).stdout
    except GitError:
        raise CheckoutError(f"{relative} is not committed on {branch}") from None
    try:
        actual = manifest_path.read_bytes()
    except OSError as exc:
        raise CheckoutError(f"cannot read {manifest_path}: {exc}") from exc
    if actual != committed:
        raise CheckoutError(
            f"{relative} differs from the version committed on {branch}"
        )
    if (
        expected_manifest is not None
        and parse_manifest(committed.decode("utf-8")) != expected_manifest
    ):
        raise CheckoutError("manifest changed while reading; run partlet publish again")


def write_site_index(store: Store, site: Site) -> None:
    projects = []
    for name in store.list_dirs(f"{site.source}/p/"):
        try:
            current = _read_json(store, f"{project_prefix(site.source, name)}/current")
            if current:
                projects.append(
                    {k: current[k] for k in ("name", "description", "tip", "updated")}
                )
        except (ValueError, KeyError, TypeError):
            # A corrupt `current` leaves that project out of the index; the
            # project's own publish reports the failure.
            continue
    projects.sort(key=lambda p: p["name"])
    _put_json(store, f"{site.source}/index.json", projects)
    store.put(
        f"{site.source}/index.html",
        render_site_index(site.base_url, projects),
        "text/html; charset=utf-8",
    )
    store.put(
        f"{site.source}/static/style.css", site_stylesheet(), "text/css; charset=utf-8"
    )


def unpublish_project(store: Store, site: Site, name: str) -> int:
    """Retire the live pointer and index entry before deleting project objects.

    A later invocation completes an interrupted removal. The trailing slash
    keeps names sharing a prefix, such as foo and foobar, independent.
    """
    if not NAME_RE.fullmatch(name) or name.endswith(".git"):
        raise ValueError(f"invalid project name {name!r}")
    prefix = f"{project_prefix(site.source, name)}/"
    keys = store.list(prefix)
    current = f"{prefix}current"
    store.delete(current)
    write_site_index(store, site)
    for key in keys:
        if key != current:
            store.delete(key)
    left = store.list(prefix)
    if left:
        raise StoreError(f"{len(left)} keys remain under {prefix}, e.g. {left[0]}")
    return len(keys)


def publish_all(
    monorepo: Path,
    manifest: Manifest,
    store: Store,
    workdir: Path,
    scanner: Scanner | None = None,
) -> list[ProjectResult]:
    """Publish every project in `manifest`; one project's failure does not stop the rest.

    `workdir` must be fresh: each project is exported to `<workdir>/<name>/export.git`,
    and an export refuses a destination that already exists.
    """
    results = []
    for project in manifest.projects.values():
        try:
            result = publish_project(
                monorepo, manifest, project, store, workdir, scanner
            )
        except Exception as e:  # noqa: BLE001 - one project must not stop the rest
            result = ProjectResult(
                project.name, "failed", reason=f"{type(e).__name__}: {e}"
            )
        results.append(result)
    write_site_index(store, manifest.site)
    return results
