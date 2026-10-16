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
from partlet.gitstatic import read_state, upload_pack, write_pointers
from partlet.gitutil import GitError, git_out
from partlet.history import HistoryError, check_history
from partlet.manifest import Manifest, Project, Site
from partlet.site.render import (
    ProjectInfo,
    render_project,
    render_site_index,
    site_stylesheet,
)
from partlet.site.tree import read_tree
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


def _run_cleanup(store: Store, prefix: str, current: dict | None) -> None:
    # cleanup.json can be stale: a publish that died after `current` but before
    # cleanup.json may have brought listed keys back to life. Never delete those.
    live = {
        key
        for pack in read_state(store, f"{prefix}/git").packs
        for key in (
            f"{prefix}/git/objects/pack/{pack}.pack",
            f"{prefix}/git/objects/pack/{pack}.idx",
        )
    }
    live_build = None
    if current:
        live_build = f"{prefix}/site/{current['build']}/"
        live |= {f"{prefix}/archive/{current['tip']}.{fmt}" for fmt in ARCHIVE_FORMATS}
    for key in _read_json(store, f"{prefix}/cleanup.json") or []:
        if key in live or (live_build and key.startswith(live_build)):
            continue
        store.delete(key)


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
        if decision.action == "unchanged" and current and current.get("build") == build:
            return ProjectResult(project.name, "unchanged", tip, decision.reason)

        _run_cleanup(store, prefix, current)
        superseded: list[str] = []

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
            superseded += plan.superseded

        updated = git_out("show", "-s", "--format=%cI", tip, cwd=repo)
        info = ProjectInfo(
            project.name, project.description, tip, site.base_url, updated
        )
        for key, data in render_project(info, read_tree(repo, tip)).items():
            store.put(f"{prefix}/site/{build}/{key}", data)
        for fmt, data in make_archives(repo, project.name, tip).items():
            store.put(f"{prefix}/archive/{tip}.{fmt}", data)

        # 2. Pointers, so refs never name objects that are not uploaded yet.
        if plan is not None:
            write_pointers(store, f"{prefix}/git", plan)
        _put_json(
            store,
            f"{prefix}/current",
            {
                "name": project.name,
                "description": project.description,
                "tip": tip,
                "build": build,
                "updated": updated,
            },
        )

        # 3. Record what is now unreferenced; the next publish deletes it.
        if current:
            if current.get("build") != build:
                superseded += store.list(f"{prefix}/site/{current['build']}/")
            if current.get("tip") != tip:
                superseded += [
                    f"{prefix}/archive/{current['tip']}.{fmt}"
                    for fmt in ARCHIVE_FORMATS
                ]
        _put_json(store, f"{prefix}/cleanup.json", sorted(set(superseded)))
        reason = "re-rendered" if decision.action == "unchanged" else decision.reason
        return ProjectResult(project.name, "published", tip, reason)
    except (ExportError, HistoryError, GitError) as e:
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
