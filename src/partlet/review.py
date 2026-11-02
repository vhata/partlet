"""`partlet review`: what to check before approving a project's export."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from partlet.export import export_project
from partlet.gitutil import git, git_out
from partlet.history import is_ancestor
from partlet.manifest import (
    SHA_RE,
    Manifest,
    Project,
    parse_manifest,
    set_project_fields,
)
from partlet.scan import GITLEAKS_VERSION, Finding, Scanner
from partlet.site.tree import SIZE_CAP


class ReviewError(Exception):
    """The review cannot run as asked."""


@dataclass(frozen=True)
class EarlierLocation:
    location: str
    renames: tuple[str, ...]  # "old path -> new path"


@dataclass(frozen=True)
class Report:
    name: str
    tip: str
    commit_count: int
    paths: tuple[tuple[str, bool], ...]  # (path, deleted at the tip)
    large_files: tuple[tuple[str, int], ...]
    authors: tuple[str, ...]
    committers: tuple[str, ...]
    findings: tuple[Finding, ...]
    earlier_locations: tuple[EarlierLocation, ...]
    published_tip: str | None
    fast_forward: bool | None  # None when nothing is published
    log: str

    def render(self) -> str:
        if self.published_tip is None:
            published = "none (first publication)"
        elif self.fast_forward:
            published = f"{self.published_tip} (fast-forward)"
        else:
            published = f"{self.published_tip} (NOT an ancestor: this is a rewrite)"
        lines = [
            f"Review of {self.name}",
            f"Export tip:    {self.tip} ({self.commit_count} commits)",
            f"Published tip: {published}",
            "",
            "Paths in history (D = deleted at the tip):",
            *(f"  {'D' if deleted else ' '} {path}" for path, deleted in self.paths),
            "",
            f"Files over {SIZE_CAP // 1024 // 1024} MiB anywhere in history:",
            *(f"  {size:>12} {path}" for path, size in self.large_files),
            *([] if self.large_files else ["  (none)"]),
            "",
            "Authors:",
            *(f"  {a}" for a in self.authors),
            "Committers:",
            *(f"  {c}" for c in self.committers),
            "",
            (
                f"Secret scan (gitleaks {GITLEAKS_VERSION}, full history): "
                f"{len(self.findings)} finding(s)"
            ),
            *(
                f"  {f.describe()}\n    fingerprint: {f.fingerprint}"
                for f in self.findings
            ),
            "",
            (
                "Undeclared earlier locations (files renamed into the project from "
                "outside path and previous_paths):"
            ),
            *(
                f"  {e.location}: consider adding it to previous_paths\n"
                + "".join(f"    {r}\n" for r in e.renames).rstrip("\n")
                for e in self.earlier_locations
            ),
            *([] if self.earlier_locations else ["  (none)"]),
            "",
            "Commits:",
            self.log,
        ]
        return "\n".join(lines) + "\n"


def _fields(raw: bytes) -> list[str]:
    return [f for f in raw.decode("utf-8", "backslashreplace").split("\0") if f]


def _root_of(path: str, roots: tuple[str, ...]) -> str | None:
    return next((r for r in roots if path == r or path.startswith(r + "/")), None)


def history_paths(repo: Path) -> tuple[tuple[str, bool], ...]:
    ever = set(
        _fields(
            git(
                "log",
                "-z",
                "--format=",
                "--name-only",
                "--no-renames",
                "-m",  # merges list their changes too, against each parent
                "refs/heads/main",
                cwd=repo,
            ).stdout
        )
    )
    now = set(
        _fields(
            git(
                "ls-tree", "-r", "-z", "--name-only", "refs/heads/main", cwd=repo
            ).stdout
        )
    )
    return tuple((path, path not in now) for path in sorted(ever | now))


def large_files(repo: Path, cap: int = SIZE_CAP) -> tuple[tuple[str, int], ...]:
    objects = git(
        "rev-list", "--objects", "--no-object-names", "refs/heads/main", cwd=repo
    ).stdout
    checked = git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        cwd=repo,
        input=objects,
    ).stdout.decode("ascii")
    oversized: dict[str, int] = {}
    for line in checked.splitlines():
        oid, kind, size = line.split()
        if kind == "blob" and int(size) > cap:
            oversized[oid] = int(size)
    if not oversized:
        return ()
    # rev-list --objects reports only one name for each object. A blob can
    # occur at several paths, so use raw history to find every affected name.
    fields = _fields(
        git(
            "log",
            "--raw",
            "--no-abbrev",
            "--format=",
            "-z",
            "--no-renames",
            "--root",
            "-m",
            "refs/heads/main",
            cwd=repo,
        ).stdout
    )
    sizes: dict[str, int] = {}
    for index in range(0, len(fields) - 1, 2):
        meta, path = fields[index].lstrip("\n").split(), fields[index + 1]
        for oid in meta[2:4]:
            if oid in oversized:
                sizes[path] = max(sizes.get(path, 0), oversized[oid])
    return tuple(sorted(sizes.items()))


def earlier_locations(
    monorepo: Path, branch: str, project: Project
) -> tuple[EarlierLocation, ...]:
    """Renames into the project's paths from anywhere else, grouped by origin."""
    fields = _fields(
        git(
            "log",
            "-z",
            "-M",
            "--diff-filter=R",
            "--name-status",
            "--format=",
            "-m",
            f"refs/heads/{branch}",
            cwd=monorepo,
        ).stdout
    )
    found: dict[str, list[str]] = {}
    for i in range(0, len(fields) - 2, 3):
        status, src, dst = fields[i].lstrip("\n"), fields[i + 1], fields[i + 2]
        root = _root_of(dst, project.all_paths)
        if not status.startswith("R") or root is None:
            continue
        if _root_of(src, project.all_paths) is not None:
            continue
        rel = dst[len(root) + 1 :]
        if src.endswith("/" + rel):
            location = src[: -len(rel) - 1]
        else:
            location = src.rpartition("/")[0] or "."
        found.setdefault(location, []).append(f"{src} -> {dst}")
    return tuple(
        EarlierLocation(loc, tuple(renames)) for loc, renames in sorted(found.items())
    )


def fetch_published_tip(base_url: str, name: str, timeout: float = 10) -> str | None:
    """Read the published tip from the public site, so review needs no credentials."""
    url = f"{base_url.rstrip('/')}/{name}/info/refs"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ReviewError(f"{url} returned an oversized refs response")
            body = raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise ReviewError(f"cannot read {url}: HTTP {e.code}") from e
    except OSError as e:
        raise ReviewError(
            f"cannot read {url}: {e}; pass --published-tip SHA, or "
            "--published-tip none if nothing is published"
        ) from e
    tips = []
    for line in body.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main" and SHA_RE.fullmatch(sha):
            tips.append(sha)
    if len(tips) == 1:
        return tips[0]
    raise ReviewError(f"{url} does not name refs/heads/main")


def build_report(
    monorepo: Path,
    manifest: Manifest,
    project: Project,
    workdir: Path,
    scanner: Scanner,
    published_tip: str | None,
) -> Report:
    site = manifest.site
    repo = workdir / "export.git"
    mailmap = monorepo / site.mailmap if site.mailmap else None
    tip = export_project(monorepo, site.branch, project, repo, mailmap)

    def people(fmt: str) -> tuple[str, ...]:
        out = git_out("log", f"--format={fmt}", "refs/heads/main", cwd=repo)
        return tuple(sorted(set(out.splitlines())))

    return Report(
        name=project.name,
        tip=tip,
        commit_count=int(git_out("rev-list", "--count", "refs/heads/main", cwd=repo)),
        paths=history_paths(repo),
        large_files=large_files(repo),
        authors=people("%an <%ae>"),
        committers=people("%cn <%ce>"),
        findings=tuple(scanner.scan(repo, workdir / "scan")),
        earlier_locations=earlier_locations(monorepo, site.branch, project),
        published_tip=published_tip,
        fast_forward=(
            None if published_tip is None else is_ancestor(repo, published_tip, tip)
        ),
        log=git_out("log", "--format=fuller", "refs/heads/main", cwd=repo),
    )


def run_review(
    monorepo: Path,
    manifest_path: Path,
    name: str,
    workdir: Path,
    *,
    scanner: Scanner,
    published_tip: str | None,
    allow_rewrite: bool,
    confirm: Callable[[str], bool],
    pager: Callable[[str], None],
) -> int:
    if published_tip is not None and not SHA_RE.fullmatch(published_tip):
        raise ReviewError("published tip must be a full commit hash or None")
    try:
        original = manifest_path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReviewError(f"cannot read {manifest_path}: {exc}") from exc
    manifest = parse_manifest(original)
    project = manifest.projects.get(name)
    if project is None:
        raise ReviewError(f"no project {name!r} in {manifest_path}")
    report = build_report(monorepo, manifest, project, workdir, scanner, published_tip)
    pager(report.render())

    if report.findings:
        print(
            f"partlet: gitleaks found {len(report.findings)} finding(s), and CI "
            "refuses to publish until they are gone from history or accepted in "
            ".gitleaks.toml or .gitleaksignore. Not approving."
        )
        return 1
    fields = {"approved": report.tip}
    if allow_rewrite:
        if report.published_tip is None:
            raise ReviewError(f"nothing is published for {name}; drop --allow-rewrite")
        if report.fast_forward:
            raise ReviewError(
                f"{report.tip[:12]} fast-forwards from the published tip; "
                "drop --allow-rewrite"
            )
        fields["allow_rewrite_of"] = report.published_tip
    elif report.fast_forward is False:
        print(
            f"partlet: {report.tip[:12]} is not a fast-forward of the published tip "
            f"{report.published_tip[:12]}; approve a rewrite with --allow-rewrite"
        )
        return 1
    if not confirm(f"Approve tip {report.tip} for publication? [y/N] "):
        print("partlet: not approved; partlet.toml is unchanged")
        return 1
    set_project_fields(manifest_path, name, fields, expected_text=original)
    print(f"partlet: approved {report.tip[:12]} in {manifest_path}; commit and push it")
    return 0
