"""Publish every approved project from a monorepo into a Store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from partlet import __version__
from partlet.archive import ARCHIVE_FORMATS, make_archives
from partlet.export import ExportError, export_project
from partlet.gitstatic import PACK_EXTS, read_state, upload_pack, write_pointers
from partlet.gitutil import GitError, git_out
from partlet.history import HistoryError, check_history
from partlet.manifest import Manifest, Project, Site
from partlet.site.render import (
    ProjectInfo,
    render_project,
    render_site_index,
    site_stylesheet,
)
from partlet.site.tree import TreeError, read_tree
from partlet.store import Store


@dataclass(frozen=True)
class ProjectResult:
    name: str
    status: Literal["published", "unchanged", "skipped", "failed"]
    tip: str | None = None
    reason: str = ""


def project_prefix(source: str, name: str) -> str:
    return f"{source}/p/{name}"


def build_id(tip: str, description: str, base_url: str) -> str:
    digest = hashlib.sha256(f"{tip}\0{description}\0{base_url}\0{__version__}".encode())
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
    """Delete every pack, site build and archive that no pointer names.

    Kept: the packs `objects/info/packs` lists, the build and archives
    `current` names, and what was live before the publish that wrote
    `current`, which it records as `previous`; that is the one publish of grace
    for superseded keys. Anything else was superseded earlier or uploaded by a
    publish that died before naming it.
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
    for area in ("git/objects/pack/", "site/", "archive/"):
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
        if decision.action == "unchanged" and current and current.get("build") == build:
            _sweep(store, prefix)
            return ProjectResult(project.name, "unchanged", tip, decision.reason)

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

        updated = git_out("show", "-s", "--format=%cI", tip, cwd=repo)
        info = ProjectInfo(
            project.name, project.description, tip, site.base_url, updated
        )
        for key, data in render_project(info, entries).items():
            store.put(f"{prefix}/site/{build}/{key}", data)
        for fmt, data in make_archives(repo, project.name, tip).items():
            store.put(f"{prefix}/archive/{tip}.{fmt}", data)

        # 2. Pointers, so refs never name objects that are not uploaded yet.
        if plan is not None:
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
    except (ExportError, HistoryError, GitError, TreeError) as e:
        return ProjectResult(project.name, "failed", tip, str(e))


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


def publish_all(
    monorepo: Path, manifest: Manifest, store: Store, workdir: Path
) -> list[ProjectResult]:
    """Publish every project in `manifest`; one project's failure does not stop the rest.

    `workdir` must be fresh: each project is exported to `<workdir>/<name>/export.git`,
    and an export refuses a destination that already exists.
    """
    results = []
    for project in manifest.projects.values():
        try:
            result = publish_project(monorepo, manifest, project, store, workdir)
        except Exception as e:  # noqa: BLE001 - one project must not stop the rest
            result = ProjectResult(
                project.name, "failed", reason=f"{type(e).__name__}: {e}"
            )
        results.append(result)
    write_site_index(store, manifest.site)
    return results
