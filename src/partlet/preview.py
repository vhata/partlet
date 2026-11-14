"""Build a disposable local site without granting publication approval."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from partlet.archive import make_archives
from partlet.export import export_project
from partlet.gitstatic import GitState, upload_pack, write_pointers
from partlet.gitutil import git_out
from partlet.manifest import Manifest
from partlet.publish import build_id, project_prefix, write_site_index
from partlet.scan import ScanError, Scanner
from partlet.site.build import build_project
from partlet.site.homepage import load_homepage
from partlet.site.models import SiteIdentity
from partlet.site.render import render_project
from partlet.site.themes import ResolvedTheme
from partlet.site.tree import read_tree
from partlet.store import LocalStore


def build_preview(
    repo: Path,
    manifest: Manifest,
    directory: Path,
    port: int,
    theme: ResolvedTheme,
    scanner: Scanner | None = None,
) -> Path:
    """Render all configured projects into a fresh, local-only object store.

    This deliberately does not call the publisher or modify approval fields.
    Every invocation starts from nothing; there is no public state to replace.
    """
    site = replace(manifest.site, base_url=f"http://127.0.0.1:{port}")
    intro_html = load_homepage(repo, site)
    out = directory / "objects"
    out.mkdir()  # Refuse reuse, including a symlink to an existing store.
    store = LocalStore(out)
    for project in manifest.projects.values():
        work = directory / "exports" / project.name
        exported = work / "export.git"
        mailmap = repo / site.mailmap if site.mailmap else None
        tip = export_project(repo, site.branch, project, exported, mailmap)
        if scanner is not None:
            findings = scanner.scan(exported, work / "scan")
            if findings:
                raise ScanError(
                    f"{project.name}: secret scan found {len(findings)} finding(s); "
                    "run partlet review to inspect them"
                )
        updated = git_out("show", "-s", "--format=%cI", tip, cwd=exported)
        info = build_project(
            project.name, project.description, tip, site.base_url, updated
        )
        identity = SiteIdentity(site.name, site.tagline)
        pages = render_project(info, read_tree(exported, tip), theme, identity)
        prefix = project_prefix(site.source, project.name)
        build = build_id(
            tip, project.description, site.base_url, theme.digest, identity
        )
        store.validate_keys(f"{prefix}/site/{build}/{key}" for key in pages)
        for key, data in pages.items():
            store.put(f"{prefix}/site/{build}/{key}", data)
        for fmt, data in make_archives(exported, project.name, tip).items():
            store.put(f"{prefix}/archive/{tip}.{fmt}", data)
        old = GitState(None, ())
        plan = upload_pack(store, f"{prefix}/git", exported, tip, old, work / "packs")
        write_pointers(store, f"{prefix}/git", plan, old)
        store.put(
            f"{prefix}/current",
            json.dumps(
                {
                    "name": project.name,
                    "description": project.description,
                    "tip": tip,
                    "build": build,
                    "updated": updated,
                }
            ).encode(),
        )
        print(f"{project.name:24} preview    {tip[:12]}", flush=True)
    write_site_index(store, site, theme, intro_html)
    return out
