# Publisher Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `partlet build --out <dir>` command that exports every approved project from a monorepo, checks its history, and writes a complete Partlet site (dumb-HTTP Git files, rendered pages, raw files, archives, site index) into a local directory, such that `git clone` and `git pull` work against that directory served by any static HTTP server.

**Architecture:** A Python package (`src/partlet`) with one module per pipeline stage: manifest, export (git filter-repo), history checks, dumb-HTTP packing, site rendering, archives, and a publish pipeline that writes through a small `Store` interface. This plan implements only the local-directory store; the R2 store, secret scanning, `partlet review`, the Worker, and the GitHub Action come in later plans.

**Tech Stack:** Python 3.12, git 2.4x+, git-filter-repo (pip), Jinja2, markdown-it-py, Pygments, pytest. Packaged with hatchling.

**Spec:** `docs/specs/2026-10-15-partlet-design.md`

### Scope within the spec

This is plan 1 of 3.

1. **Publisher core (this plan).** Manifest, export, history checks, packs and pointers, site, archives, publish pipeline, local store, `partlet build`.
2. **Worker.** TypeScript Worker: routing, R2 reads, caching, raw content-type policy, dumb-HTTP `info/refs`, tests on the Workers pool.
3. **Publishing to R2.** R2 store, gitleaks scanning, `partlet review`, `partlet publish` and `unpublish`, step summary, composite `action.yml`, end-to-end test through `wrangler dev` and its CI job.

## Global Constraints

- Python `>=3.12`. Each worktree has its own `.venv`, created by `bash scripts/setup.sh` (Task 1). Run tests with `bash scripts/test.sh` or `.venv/bin/pytest`.
- Before every commit, `bash scripts/check.sh` passes: ruff format check, shellcheck plus ruff lint, and the test suite. Run `.venv/bin/ruff format src tests` to fix formatting.
- Project names match `[a-z0-9][a-z0-9._-]*`; names ending in `.git` are rejected.
- Exports keep only `refs/heads/main`, whatever the monorepo's publishing branch is called.
- Given the same monorepo history, path list, mailmap and tool versions, an export produces identical commit hashes.
- A missing `path` at the tip of the publishing branch fails the project; it never publishes an empty tree.
- Consolidate packs when a project has more than 20 packs (`MAX_PACKS = 20`).
- Files that are binary or larger than 1 MiB (`SIZE_CAP = 1024 * 1024`) get no viewer page, only a raw link.
- Rendered pages contain no JavaScript. Markdown raw HTML is escaped, never passed through.
- Generated links are root-relative: `/<name>`, `/<name>/tree/<dir>`, `/<name>/blob/<path>`, `/<name>/raw/<path>`, `/<name>/archive/<name>.<fmt>`, stylesheet at `/_partlet/style.css`.
- Store keys (all under `<source>/`):
  - `index.html`, `index.json`, `static/style.css`
  - `p/<name>/current`, `p/<name>/cleanup.json`
  - `p/<name>/git/HEAD`, `p/<name>/git/info/refs`, `p/<name>/git/objects/info/packs`, `p/<name>/git/objects/pack/pack-*.{pack,idx}`
  - `p/<name>/site/<build>/...`
  - `p/<name>/archive/<sha>.{tar.gz,zip}`
- Upload order within a project: pack files, site build, archives, then pointers (`objects/info/packs`, `info/refs`, `HEAD`), then `current`, then `cleanup.json`.
- Commit messages: imperative subject, no attribution trailers.
- The repository follows `docket/CONTRACT.md` and the Docket section of `AGENTS.md`; this plan is implemented on a branch through a PR, not on `main`.

## Review Focus

1. **README containing raw HTML or `<script>`** must render escaped, not as live markup. Test in Task 6.
2. **Relative links and images in a README** (`docs/x.md`, `../y`, `img.png`, `sub/`) must point at the right `blob/`, `tree/` or `raw/` URL for the directory the README sits in, and links that escape the project root are left unchanged. Test in Task 6.
3. **File names with spaces, `#`, `?`, `%` or non-ASCII characters** must produce working, percent-encoded links and be stored under their real names. Test in Task 7.
4. **Symlinks in a project**, including ones pointing outside it, are shown as link text and never followed. Test in Task 7.
5. **Running `partlet build` twice with no changes** reports `unchanged`, uploads no new pack, and leaves a cloneable repo. Test in Task 9.

Also guarded, with tests in the owning tasks: shallow monorepo clones (Task 2), neighbouring directories with a shared prefix such as `tools/foo` and `tools/foobar` (Task 2), and unknown manifest keys such as a misspelt `previous_path` (Task 1).

---

## File structure

```
pyproject.toml
scripts/              setup.sh, check.sh, fmt-check.sh, lint.sh, test.sh (docket gates)
.githooks/            pre-commit (fast gates), pre-push (full check)
.github/workflows/ci.yml
docs/QUALITY.md
src/partlet/
  __init__.py          __version__
  manifest.py          Site, Project, Manifest, load_manifest, parse_manifest, ManifestError
  gitutil.py           git(), git_out(), GitError
  export.py            export_project(), ExportError
  history.py           check_history(), Decision, HistoryError
  store.py             Store protocol, LocalStore
  gitstatic.py         GitState, PackPlan, read_state(), upload_pack(), write_pointers()
  archive.py           ARCHIVE_FORMATS, make_archives()
  site/
    __init__.py
    tree.py            FileEntry, read_tree(), is_binary(), is_viewable(), SIZE_CAP
    urls.py            tree_url(), blob_url(), raw_url(), archive_url()
    links.py           Linker
    markdown.py        render_markdown()
    highlight.py       highlight_file(), pygments_css()
    render.py          ProjectInfo, render_project(), render_site_index(), site_stylesheet()
    templates/         base.html, tree.html, blob.html, index.html
    style.css
  publish.py           ProjectResult, build_id(), publish_project(), publish_all(), write_site_index()
  cli.py               main()
tests/
  conftest.py          fixtures: mono, serve
  helpers.py           Repo builder, serve_directory()
  test_manifest.py
  test_export.py
  test_history.py
  test_store.py
  test_gitstatic.py
  test_site_content.py
  test_render.py
  test_archive.py
  test_publish.py
  test_cli.py
```

---

### Task 1: Project scaffolding and manifest

**Files:**
- Create: `pyproject.toml`, `src/partlet/__init__.py`, `src/partlet/manifest.py`, `scripts/fmt-check.sh`, `scripts/test.sh`, `.githooks/pre-push`
- Modify: `scripts/setup.sh`, `scripts/check.sh`, `scripts/lint.sh`, `.githooks/pre-commit`, `.github/workflows/ci.yml`, `docs/QUALITY.md`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `partlet.__version__: str`
  - `class ManifestError(Exception)`
  - `@dataclass(frozen=True) class Site(source: str, branch: str, base_url: str, mailmap: str | None)`
  - `@dataclass(frozen=True) class Project(name: str, path: str, previous_paths: tuple[str, ...], description: str, approved: str | None, allow_rewrite_of: str | None)` with property `all_paths -> tuple[str, ...]` (path first)
  - `@dataclass(frozen=True) class Manifest(site: Site, projects: dict[str, Project])`
  - `parse_manifest(text: str) -> Manifest`, `load_manifest(path: Path) -> Manifest`

- [ ] **Step 1: Create the packaging files and virtualenv**

The repository already has a `.gitignore` covering `.venv/`, Python caches and build output; leave it as is.

`pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "partlet"
dynamic = ["version"]
description = "Publish selected directories of a private monorepo as read-only Git repositories"
requires-python = ">=3.12"
dependencies = [
  "git-filter-repo>=2.38",
  "jinja2>=3.1",
  "markdown-it-py>=3.0",
  "pygments>=2.18",
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.6"]

[project.scripts]
partlet = "partlet.cli:main"

[tool.hatch.version]
path = "src/partlet/__init__.py"

[tool.hatch.build.targets.wheel]
packages = ["src/partlet"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tests"]
```

`src/partlet/__init__.py`:

```python
"""Partlet: publish selected monorepo directories as read-only Git repositories."""

__version__ = "0.1.0"
```

In `scripts/setup.sh`, replace the line `# Python and Worker dependencies are added here as those components land.` with `# Worker dependencies are added here when the Worker lands.`, and insert this block after `cd "$(dirname "$0")/.."`:

```bash
# Python: a virtualenv per worktree with the package installed editable.
# uv finds or downloads a Python 3.12 interpreter.
command -v uv >/dev/null || { echo "setup: uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }
[ -d .venv ] || uv venv --quiet --python 3.12 .venv
uv pip install --quiet --python .venv/bin/python -e '.[dev]'
```

Run: `bash scripts/setup.sh`

Expected: `setup: done.`; `.venv/bin/python -c "import partlet; print(partlet.__version__)"` prints `0.1.0`.

- [ ] **Step 2: Write the failing manifest tests**

`tests/test_manifest.py`:

```python
import pytest

from partlet.manifest import ManifestError, parse_manifest

FULL = """
[site]
source = "jonathan"
branch = "trunk"
base_url = "https://partlet.example/"
mailmap = ".partlet-mailmap"

[projects.foo]
path = "/tools/foo/"
previous_paths = ["scripts/foo"]
description = "Foo tool"
approved = "3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a"
allow_rewrite_of = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[projects.bar]
path = "bar"
"""


def test_full_manifest_parses():
    m = parse_manifest(FULL)
    assert m.site.source == "jonathan"
    assert m.site.branch == "trunk"
    assert m.site.base_url == "https://partlet.example"
    assert m.site.mailmap == ".partlet-mailmap"
    foo = m.projects["foo"]
    assert foo.path == "tools/foo"
    assert foo.previous_paths == ("scripts/foo",)
    assert foo.all_paths == ("tools/foo", "scripts/foo")
    assert foo.description == "Foo tool"
    assert foo.approved == "3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a"
    assert foo.allow_rewrite_of == "a" * 40


def test_defaults():
    m = parse_manifest('[site]\nsource = "s"\nbase_url = "https://x"\n[projects.bar]\npath = "bar"\n')
    assert m.site.branch == "main"
    assert m.site.mailmap is None
    bar = m.projects["bar"]
    assert bar.previous_paths == ()
    assert bar.description == ""
    assert bar.approved is None
    assert bar.allow_rewrite_of is None


def test_no_projects_is_valid():
    m = parse_manifest('[site]\nsource = "s"\nbase_url = "https://x"\n')
    assert m.projects == {}


@pytest.mark.parametrize(
    "body, message",
    [
        ('[projects.foo]\npath = "foo"\n', "missing [site]"),
        ('[site]\nsource = "s"\n', "base_url"),
        ('[site]\nsource = "Bad"\nbase_url = "https://x"\n', "site.source"),
        ('[site]\nsource = "s"\nbase_url = "https://x"\ncolour = "red"\n', "unknown key"),
    ],
)
def test_bad_site(body, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(body)


SITE = '[site]\nsource = "s"\nbase_url = "https://x"\n'


@pytest.mark.parametrize(
    "project, message",
    [
        ('[projects.Foo]\npath = "foo"\n', "project name"),
        ('[projects."foo.git"]\npath = "foo"\n', "\\.git"),
        ('[projects.foo]\ndescription = "x"\n', "path"),
        ('[projects.foo]\npath = "../foo"\n', "invalid path"),
        ('[projects.foo]\npath = "a/./b"\n', "invalid path"),
        ('[projects.foo]\npath = "/"\n', "invalid path"),
        ('[projects.foo]\npath = "foo"\napproved = "abc"\n', "approved"),
        ('[projects.foo]\npath = "foo"\nprevious_path = ["old"]\n', "unknown key"),
        ('[projects.foo]\npath = "foo"\nprevious_paths = "old"\n', "previous_paths"),
        ('[projects.foo]\npath = "foo"\nprevious_paths = ["foo"]\n', "duplicate"),
        ('[projects.foo]\npath = "foo"\nprevious_paths = ["old", "old/"]\n', "duplicate"),
    ],
)
def test_bad_project(project, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(SITE + project)


def test_invalid_toml():
    with pytest.raises(ManifestError, match="invalid TOML"):
        parse_manifest("[site\n")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.manifest'`.

- [ ] **Step 4: Implement the manifest module**

`src/partlet/manifest.py`:

```python
"""Load and validate partlet.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

NAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
SHA_RE = re.compile(r"[0-9a-f]{40}")

SITE_KEYS = {"source", "branch", "base_url", "mailmap"}
PROJECT_KEYS = {"path", "previous_paths", "description", "approved", "allow_rewrite_of"}


class ManifestError(Exception):
    """partlet.toml is missing, malformed, or fails validation."""


@dataclass(frozen=True)
class Site:
    source: str
    branch: str
    base_url: str
    mailmap: str | None = None


@dataclass(frozen=True)
class Project:
    name: str
    path: str
    previous_paths: tuple[str, ...] = ()
    description: str = ""
    approved: str | None = None
    allow_rewrite_of: str | None = None

    @property
    def all_paths(self) -> tuple[str, ...]:
        return (self.path, *self.previous_paths)


@dataclass(frozen=True)
class Manifest:
    site: Site
    projects: dict[str, Project]


def load_manifest(path: Path) -> Manifest:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ManifestError(f"cannot read {path}: {e}") from e
    return parse_manifest(text)


def parse_manifest(text: str) -> Manifest:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"invalid TOML: {e}") from e
    site = _parse_site(data.get("site"))
    raw_projects = data.get("projects", {})
    if not isinstance(raw_projects, dict):
        raise ManifestError("[projects] must be a table")
    projects = {name: _parse_project(name, body) for name, body in raw_projects.items()}
    return Manifest(site=site, projects=projects)


def normalize_path(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{where}: path must be a string")
    if "\\" in value:
        raise ManifestError(f"{where}: invalid path {value!r}")
    parts = PurePosixPath(value.strip("/")).parts
    if not parts or parts == (".",) or any(p in (".", "..") for p in parts):
        raise ManifestError(f"{where}: invalid path {value!r}")
    # PurePosixPath collapses "a/./b" to "a/b", so check the raw segments too.
    if any(seg in (".", "..") for seg in value.strip("/").split("/")):
        raise ManifestError(f"{where}: invalid path {value!r}")
    return "/".join(parts)


def _check_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown key(s) {', '.join(unknown)}")


def _str(raw: dict[str, Any], key: str, where: str, default: str | None = None) -> str | None:
    value = raw.get(key, default)
    if value is not None and not isinstance(value, str):
        raise ManifestError(f"{where}.{key} must be a string")
    return value


def _sha(raw: dict[str, Any], key: str, where: str) -> str | None:
    value = _str(raw, key, where)
    if value is not None and not SHA_RE.fullmatch(value):
        raise ManifestError(f"{where}.{key} must be a full 40-character commit hash")
    return value


def _parse_site(raw: Any) -> Site:
    if not isinstance(raw, dict):
        raise ManifestError("missing [site] table")
    _check_keys(raw, SITE_KEYS, "site")
    source = _str(raw, "source", "site")
    if source is None or not NAME_RE.fullmatch(source):
        raise ManifestError(f"site.source must match {NAME_RE.pattern}")
    base_url = _str(raw, "base_url", "site")
    if not base_url:
        raise ManifestError("site.base_url is required")
    return Site(
        source=source,
        branch=_str(raw, "branch", "site", "main"),
        base_url=base_url.rstrip("/"),
        mailmap=_str(raw, "mailmap", "site"),
    )


def _parse_project(name: str, raw: Any) -> Project:
    where = f"projects.{name}"
    if not NAME_RE.fullmatch(name):
        raise ManifestError(f"project name {name!r} must match {NAME_RE.pattern}")
    if name.endswith(".git"):
        raise ManifestError(f"project name {name!r} must not end in .git")
    if not isinstance(raw, dict):
        raise ManifestError(f"{where} must be a table")
    _check_keys(raw, PROJECT_KEYS, where)
    if "path" not in raw:
        raise ManifestError(f"{where}.path is required")
    path = normalize_path(raw["path"], f"{where}.path")
    previous_raw = raw.get("previous_paths", [])
    if not isinstance(previous_raw, list):
        raise ManifestError(f"{where}.previous_paths must be a list of strings")
    previous = tuple(normalize_path(p, f"{where}.previous_paths") for p in previous_raw)
    all_paths = (path, *previous)
    if len(set(all_paths)) != len(all_paths):
        raise ManifestError(f"{where}: duplicate entries in path and previous_paths")
    return Project(
        name=name,
        path=path,
        previous_paths=previous,
        description=_str(raw, "description", where, "") or "",
        approved=_sha(raw, "approved", where),
        allow_rewrite_of=_sha(raw, "allow_rewrite_of", where),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_manifest.py -v`
Expected: all PASS.

- [ ] **Step 6: Wire the Python gates into the docket scripts**

`scripts/fmt-check.sh`:

```bash
#!/usr/bin/env bash
# Check Python formatting with ruff; never rewrites.
# Fix with: .venv/bin/ruff format src tests
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/ruff format --check "$@" src tests
```

`scripts/test.sh`:

```bash
#!/usr/bin/env bash
# Run the Python test suite. pytest exits 5 when it collects no tests,
# so an empty suite fails this gate.
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/pytest -q "$@"
```

In `scripts/lint.sh`, change the header comment to:

```bash
# Lint the project's own shell scripts with shellcheck and the Python code
# with ruff. docket/ is vendored and checked upstream, so it is not linted
# here. Extra arguments go to ruff.
```

and replace the last two lines (`shellcheck "$@" "${files[@]}"` and the `echo`) with:

```bash
shellcheck "${files[@]}"
echo "lint: ${#files[@]} shell scripts clean"
.venv/bin/ruff check "$@" src tests
```

In `scripts/check.sh`, replace `gates=(lint)` with `gates=(fmt-check lint test)`.

The test suite clones real repositories, so it moves off the commit hook. Replace the body of `.githooks/pre-commit` after `cd "$(git rev-parse --show-toplevel)"` with:

```bash
bash scripts/fmt-check.sh
bash scripts/lint.sh
bash docket/scripts/check-queues.sh --strict
bash docket/scripts/check-links.sh
```

and change its header comment's first line to `# Fast gates on the whole working tree, not just the staged files; it only`.

`.githooks/pre-push`:

```bash
#!/usr/bin/env bash
# Full check before anything leaves the machine. Installed by scripts/setup.sh.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

bash scripts/check.sh
```

In `.github/workflows/ci.yml`, in the `check` job, replace the comment above `- run: bash scripts/setup.sh` with:

```yaml
      # shellcheck is preinstalled on ubuntu-latest; uv provides Python.
      - uses: astral-sh/setup-uv@v6
```

In `docs/QUALITY.md`:

- Replace the `scripts/lint.sh` and `scripts/check.sh` rows of the gates table with:

  ```markdown
  | `scripts/fmt-check.sh` | `ruff format --check` over `src` and `tests` | yes | via `check.sh` | via `check.sh` | via `check.sh` | |
  | `scripts/lint.sh` | shellcheck over `scripts/*.sh` and `.githooks/*`, then `ruff check` over `src` and `tests` | yes | via `check.sh` | via `check.sh` | via `check.sh` | |
  | `scripts/test.sh` | pytest; fails on an empty collection | | via `check.sh` | via `check.sh` | via `check.sh` | |
  | `scripts/check.sh` | the gates in its `gates` array, in order: `fmt-check`, `lint`, `test` | | yes | yes | yes | |
  ```

- Replace the sentence starting "There is no Python or Worker code yet" with: "There is no Worker code yet, so it has no gates; they join `scripts/check.sh`, `ci.yml` and this table in the PR that adds the Worker."
- Replace the hooks paragraph with: "Hooks are a tracked `.githooks/` directory, wired with `git config core.hooksPath .githooks` by `bash scripts/setup.sh`. Pre-commit runs the format check, lint and the queue and link validators on the whole working tree; it only checks and never rewrites files. Pre-push runs `bash scripts/check.sh`, including the test suite. Bypassing a hook is for a broken toolchain only; state the bypass and the equivalent checks in the PR."
- Replace "Toolchain pins: none yet." with: "Toolchain pins: Python 3.12 (`scripts/setup.sh`); dependency floors in `pyproject.toml`. Bumping a pin is its own PR."
- In Review inputs, replace "Baseline commands beyond `bash scripts/check.sh`: none yet." with "Baseline commands beyond `bash scripts/check.sh`: `partlet build --out <dir>` against a synthetic monorepo, then `git clone` from that directory served over HTTP."

Run: `chmod +x scripts/*.sh .githooks/*`, then `.venv/bin/ruff format src tests` and `bash scripts/check.sh`

Expected: `check: all gates passed`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/partlet/__init__.py src/partlet/manifest.py tests/test_manifest.py \
  scripts .githooks .github/workflows/ci.yml docs/QUALITY.md
git commit -m "Add package scaffolding, manifest parser and Python gates"
```

---

### Task 2: Git helpers, test repo builder, and export

**Files:**
- Create: `src/partlet/gitutil.py`, `src/partlet/export.py`, `tests/helpers.py`, `tests/conftest.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Project` from Task 1.
- Produces:
  - `class GitError(Exception)`
  - `git(*args: str, cwd: Path, input: bytes | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]` (raises `GitError` on non-zero exit)
  - `git_out(*args: str, cwd: Path, input: bytes | None = None) -> str` (stdout, decoded, stripped)
  - `run_filter_repo(*args: str, cwd: Path) -> None`
  - `class ExportError(Exception)`
  - `export_project(monorepo: Path, branch: str, project: Project, dest: Path, mailmap: Path | None = None) -> str` (returns the export tip SHA; `dest` is a bare repo whose only ref is `refs/heads/main`)
  - tests: `helpers.Repo(path)` with `.write(rel, content)`, `.mv(src, dst)`, `.rm(rel)`, `.commit(message) -> str`, `.path`; `helpers.serve_directory(root) -> ContextManager[str]` (base URL); conftest fixtures `mono` (a fresh `Repo`) and `serve` (the `serve_directory` function).

- [ ] **Step 1: Write the git helpers**

`src/partlet/gitutil.py`:

```python
"""Thin wrappers around the git command line."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class GitError(Exception):
    """A git command failed."""


def git(
    *args: str,
    cwd: Path,
    input: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    return _run(["git", *args], cwd=cwd, input=input, env=env)


def git_out(*args: str, cwd: Path, input: bytes | None = None) -> str:
    return git(*args, cwd=cwd, input=input).stdout.decode("utf-8").strip()


def run_filter_repo(*args: str, cwd: Path) -> None:
    """Run the git-filter-repo installed alongside this package."""
    _run([sys.executable, "-m", "git_filter_repo", *args], cwd=cwd)


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    input: bytes | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    full_env = {**os.environ, **(env or {})}
    proc = subprocess.run(cmd, cwd=cwd, input=input, env=full_env, capture_output=True)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"{' '.join(cmd[:3])}... failed ({proc.returncode}): {stderr}")
    return proc
```

- [ ] **Step 2: Write the test helpers**

`tests/helpers.py`:

```python
"""Helpers for building throwaway git repositories and serving directories."""

from __future__ import annotations

import functools
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from partlet.gitutil import git, git_out

EPOCH = 1767225600  # 2026-01-01T00:00:00Z


class Repo:
    """A non-bare repository with deterministic commit timestamps."""

    def __init__(self, path: Path, branch: str = "main"):
        self.path = path
        self._tick = 0
        path.mkdir(parents=True)
        git("init", "-q", "-b", branch, cwd=path)
        git("config", "user.name", "Test Author", cwd=path)
        git("config", "user.email", "author@example.com", cwd=path)
        git("config", "commit.gpgsign", "false", cwd=path)

    def write(self, rel: str, content: str | bytes) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        target.write_bytes(content)

    def symlink(self, rel: str, target: str) -> None:
        link = self.path / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)

    def mv(self, src: str, dst: str) -> None:
        (self.path / dst).parent.mkdir(parents=True, exist_ok=True)
        git("mv", src, dst, cwd=self.path)

    def rm(self, rel: str) -> None:
        git("rm", "-r", "-q", rel, cwd=self.path)

    def commit(self, message: str) -> str:
        self._tick += 1
        date = f"{EPOCH + self._tick * 60} +0000"
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        git("add", "-A", cwd=self.path)
        git("commit", "-q", "--allow-empty", "-m", message, cwd=self.path, env=env)
        return git_out("rev-parse", "HEAD", cwd=self.path)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - signature fixed by base class
        pass


@contextmanager
def serve_directory(root: Path) -> Iterator[str]:
    """Serve `root` over plain HTTP on a free port; yields the base URL."""
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
```

`tests/conftest.py`:

```python
import pytest

from helpers import Repo, serve_directory


@pytest.fixture
def mono(tmp_path):
    return Repo(tmp_path / "mono")


@pytest.fixture
def serve():
    return serve_directory
```

`helpers` is importable from tests because Task 1 set `pythonpath = ["tests"]` in `pyproject.toml`.

- [ ] **Step 3: Write the failing export tests**

`tests/test_export.py`:

```python
import pytest

from partlet.export import ExportError, export_project
from partlet.gitutil import git, git_out
from partlet.manifest import Project


def files_at(repo, rev="refs/heads/main"):
    return sorted(git_out("ls-tree", "-r", "--name-only", rev, cwd=repo).splitlines())


def subjects(repo):
    return git_out("log", "--format=%s", "refs/heads/main", cwd=repo).splitlines()


def make_basic(mono):
    mono.write("tools/foo/a.txt", "one\n")
    mono.write("tools/foobar/b.txt", "neighbour\n")
    mono.write("other/x.txt", "x\n")
    mono.commit("c1")
    mono.write("tools/foo/a.txt", "one\ntwo\n")
    mono.commit("c2 touches foo")
    mono.write("other/x.txt", "x\ny\n")
    mono.commit("c3 only other")


def test_export_keeps_only_project_files_at_root(mono, tmp_path):
    make_basic(mono)
    tip = export_project(mono.path, "main", Project("foo", "tools/foo"), tmp_path / "e.git")
    repo = tmp_path / "e.git"
    assert files_at(repo) == ["a.txt"]
    assert subjects(repo) == ["c2 touches foo", "c1"]
    assert git_out("rev-parse", "refs/heads/main", cwd=repo) == tip
    assert git_out("symbolic-ref", "HEAD", cwd=repo) == "refs/heads/main"
    refs = git_out("for-each-ref", "--format=%(refname)", cwd=repo).splitlines()
    assert refs == ["refs/heads/main"]


def test_export_is_deterministic(mono, tmp_path):
    make_basic(mono)
    a = export_project(mono.path, "main", Project("foo", "tools/foo"), tmp_path / "a.git")
    b = export_project(mono.path, "main", Project("foo", "tools/foo"), tmp_path / "b.git")
    assert a == b


def test_move_with_previous_paths_fast_forwards(mono, tmp_path):
    mono.write("scripts/foo/a.txt", "one\n")
    mono.commit("c1")
    mono.write("scripts/foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    before = export_project(mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "before.git")

    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    mono.write("tools/foo/a.txt", "one\ntwo\nthree\n")
    mono.commit("c3")
    moved = Project("foo", "tools/foo", previous_paths=("scripts/foo",))
    after = export_project(mono.path, "main", moved, tmp_path / "after.git")

    repo = tmp_path / "after.git"
    git("merge-base", "--is-ancestor", before, after, cwd=repo)  # raises if not
    assert subjects(repo) == ["c3", "c2", "c1"]  # the move commit is pruned


def test_branch_is_renamed_to_main(tmp_path):
    from helpers import Repo

    mono = Repo(tmp_path / "mono", branch="trunk")
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    export_project(mono.path, "trunk", Project("foo", "foo"), tmp_path / "e.git")
    refs = git_out("for-each-ref", "--format=%(refname)", cwd=tmp_path / "e.git").splitlines()
    assert refs == ["refs/heads/main"]


def test_missing_directory_fails_with_hint(mono, tmp_path):
    mono.write("scripts/foo/a.txt", "a\n")
    mono.commit("c1")
    mono.mv("scripts/foo", "tools/foo")
    mono.commit("move")
    with pytest.raises(ExportError, match="previous_paths"):
        export_project(mono.path, "main", Project("foo", "scripts/foo"), tmp_path / "e.git")


def test_path_that_is_a_file_fails(mono, tmp_path):
    mono.write("foo", "i am a file\n")
    mono.commit("c1")
    with pytest.raises(ExportError, match="not a directory"):
        export_project(mono.path, "main", Project("foo", "foo"), tmp_path / "e.git")


def test_shallow_monorepo_is_rejected(mono, tmp_path):
    make_basic(mono)
    shallow = tmp_path / "shallow"
    git("clone", "-q", "--depth", "1", f"file://{mono.path}", str(shallow), cwd=tmp_path)
    with pytest.raises(ExportError, match="shallow"):
        export_project(shallow, "main", Project("foo", "tools/foo"), tmp_path / "e.git")


def test_mailmap_rewrites_author(mono, tmp_path):
    make_basic(mono)
    mailmap = tmp_path / "mailmap"
    mailmap.write_text("Public Name <public@example.com> <author@example.com>\n")
    export_project(mono.path, "main", Project("foo", "tools/foo"), tmp_path / "e.git", mailmap)
    authors = set(git_out("log", "--format=%an <%ae>", "refs/heads/main", cwd=tmp_path / "e.git").splitlines())
    assert authors == {"Public Name <public@example.com>"}
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.export'`.

- [ ] **Step 5: Implement export**

`src/partlet/export.py`:

```python
"""Extract one project's history from the monorepo with git filter-repo."""

from __future__ import annotations

from pathlib import Path

from partlet.gitutil import GitError, git, git_out, run_filter_repo
from partlet.manifest import Project


class ExportError(Exception):
    """The project cannot be exported from the monorepo as configured."""


def export_project(
    monorepo: Path,
    branch: str,
    project: Project,
    dest: Path,
    mailmap: Path | None = None,
) -> str:
    """Create a bare repo at `dest` holding only `project`'s history; return its tip."""
    if git_out("rev-parse", "--is-shallow-repository", cwd=monorepo) == "true":
        raise ExportError(
            f"{monorepo} is a shallow clone; publishing needs full history "
            "(use fetch-depth: 0 in actions/checkout)"
        )
    _require_directory(monorepo, branch, project.path)

    git(
        "clone", "--quiet", "--bare", "--no-local", "--no-tags",
        "--single-branch", "--branch", branch,
        str(monorepo.resolve()), str(dest),
        cwd=monorepo,
    )
    args = ["--quiet", "--force", "--replace-refs", "delete-no-add"]
    for path in project.all_paths:
        args += ["--path", f"{path}/", "--path-rename", f"{path}/:"]
    if mailmap is not None:
        args += ["--mailmap", str(mailmap.resolve())]
    run_filter_repo(*args, cwd=dest)

    if branch != "main":
        git("branch", "-m", branch, "main", cwd=dest)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=dest)
    return git_out("rev-parse", "refs/heads/main", cwd=dest)


def _require_directory(monorepo: Path, branch: str, path: str) -> None:
    proc_type = _object_type(monorepo, f"{branch}:{path}")
    if proc_type is None:
        raise ExportError(
            f"{path!r} does not exist on {branch}. If the directory moved, set path "
            "to its new location and add the old one to previous_paths."
        )
    if proc_type != "tree":
        raise ExportError(f"{path!r} on {branch} is not a directory")


def _object_type(repo: Path, rev: str) -> str | None:
    try:
        return git_out("cat-file", "-t", rev, cwd=repo)
    except GitError:
        return None
```

Note: `--replace-refs delete-no-add` stops filter-repo from leaving `refs/replace/*` behind, which would otherwise be published as extra refs.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: all PASS. `test_export_keeps_only_project_files_at_root` also proves `tools/foobar` is excluded, because `--path tools/foo/` carries a trailing slash.

- [ ] **Step 7: Commit**

```bash
git add src/partlet/gitutil.py src/partlet/export.py tests/helpers.py tests/conftest.py tests/test_export.py
git commit -m "Export project history with git filter-repo"
```

---

### Task 3: History checks

**Files:**
- Create: `src/partlet/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Consumes: `git` from Task 2; `export_project` and `helpers.Repo` in tests.
- Produces:
  - `class HistoryError(Exception)`
  - `@dataclass(frozen=True) class Decision(action: Literal["publish", "unchanged", "rewrite"], reason: str)`
  - `is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool` (false if `ancestor` is not in `repo`)
  - `check_history(repo: Path, new_tip: str, published_tip: str | None, approved: str | None, allow_rewrite_of: str | None) -> Decision`

- [ ] **Step 1: Write the failing tests**

`tests/test_history.py`:

```python
import pytest

from partlet.export import export_project
from partlet.gitutil import git_out
from partlet.history import HistoryError, check_history, is_ancestor
from partlet.manifest import Project


@pytest.fixture
def chain(mono, tmp_path):
    """An export with three commits; returns (repo, [c1, c2, c3])."""
    for i in range(3):
        mono.write("foo/a.txt", f"{i}\n")
        mono.commit(f"c{i}")
    repo = tmp_path / "e.git"
    export_project(mono.path, "main", Project("foo", "foo"), repo)
    shas = git_out("rev-list", "--reverse", "refs/heads/main", cwd=repo).splitlines()
    return repo, shas


def test_is_ancestor(chain):
    repo, (c1, c2, c3) = chain
    assert is_ancestor(repo, c1, c3)
    assert not is_ancestor(repo, c3, c1)
    assert not is_ancestor(repo, "f" * 40, c3)


def test_first_publish_requires_approved_ancestor(chain):
    repo, (c1, c2, c3) = chain
    assert check_history(repo, c3, None, c2, None).action == "publish"
    assert check_history(repo, c3, None, c3, None).action == "publish"
    with pytest.raises(HistoryError, match="approved"):
        check_history(repo, c3, None, "f" * 40, None)


def test_not_approved_is_an_error(chain):
    repo, (c1, c2, c3) = chain
    with pytest.raises(HistoryError, match="not approved"):
        check_history(repo, c3, None, None, None)


def test_fast_forward_publishes(chain):
    repo, (c1, c2, c3) = chain
    assert check_history(repo, c3, c2, c1, None).action == "publish"


def test_same_tip_is_unchanged(chain):
    repo, (c1, c2, c3) = chain
    assert check_history(repo, c3, c3, c1, None).action == "unchanged"


def test_non_fast_forward_is_rejected(chain):
    repo, (c1, c2, c3) = chain
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c3, "e" * 40, c1, None)
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c2, c3, c1, None)


def test_allow_rewrite_of_permits_exactly_that_tip(chain):
    repo, (c1, c2, c3) = chain
    old = "e" * 40
    assert check_history(repo, c3, old, c3, old).action == "rewrite"
    with pytest.raises(HistoryError, match="rewrite"):
        check_history(repo, c3, old, c3, "d" * 40)


def test_allow_rewrite_still_requires_approval_ancestry(chain):
    repo, (c1, c2, c3) = chain
    old = "e" * 40
    with pytest.raises(HistoryError, match="approved"):
        check_history(repo, c3, old, "f" * 40, old)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.history'`.

- [ ] **Step 3: Implement**

`src/partlet/history.py`:

```python
"""Decide whether a new export may replace what is already published."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from partlet.gitutil import GitError, git


class HistoryError(Exception):
    """The new export must not be published."""


@dataclass(frozen=True)
class Decision:
    action: Literal["publish", "unchanged", "rewrite"]
    reason: str


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    try:
        git("cat-file", "-e", f"{ancestor}^{{commit}}", cwd=repo)
        git("merge-base", "--is-ancestor", ancestor, descendant, cwd=repo)
    except GitError:
        return False
    return True


def check_history(
    repo: Path,
    new_tip: str,
    published_tip: str | None,
    approved: str | None,
    allow_rewrite_of: str | None,
) -> Decision:
    if approved is None:
        raise HistoryError("project is not approved; run partlet review")
    if published_tip == new_tip:
        return Decision("unchanged", "already published")
    if published_tip is not None and is_ancestor(repo, published_tip, new_tip):
        return Decision("publish", f"fast-forward from {published_tip[:12]}")
    if published_tip is not None and allow_rewrite_of != published_tip:
        raise HistoryError(
            f"history rewrite: published tip {published_tip[:12]} is not an ancestor of "
            f"{new_tip[:12]}; run partlet review --allow-rewrite if this is intended"
        )
    if not is_ancestor(repo, approved, new_tip):
        raise HistoryError(
            f"approved commit {approved[:12]} is not in the history of {new_tip[:12]}; "
            "re-run partlet review"
        )
    if published_tip is None:
        return Decision("publish", "first publication")
    return Decision("rewrite", f"rewrite of {published_tip[:12]} allowed by manifest")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_history.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/history.py tests/test_history.py
git commit -m "Add approval and fast-forward history checks"
```

---

### Task 4: Store interface and local directory store

**Files:**
- Create: `src/partlet/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Store(Protocol)` with `get(key: str) -> bytes | None`, `put(key: str, data: bytes, content_type: str | None = None) -> None`, `delete(key: str) -> None` (missing keys are fine), `list(prefix: str) -> list[str]` (all keys starting with `prefix`, sorted), `list_dirs(prefix: str) -> list[str]` (immediate child "directory" names under `prefix`, which must end in `/`, sorted)
  - `class LocalStore(root: Path)` implementing `Store`; rejects keys that are empty, absolute, or contain empty, `.` or `..` segments with `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_store.py`:

```python
import pytest

from partlet.store import LocalStore


def test_put_get_delete(tmp_path):
    s = LocalStore(tmp_path)
    assert s.get("a/b.txt") is None
    s.put("a/b.txt", b"hello")
    assert s.get("a/b.txt") == b"hello"
    assert (tmp_path / "a" / "b.txt").read_bytes() == b"hello"
    s.put("a/b.txt", b"again")
    assert s.get("a/b.txt") == b"again"
    s.delete("a/b.txt")
    s.delete("a/b.txt")
    assert s.get("a/b.txt") is None


def test_list_and_list_dirs(tmp_path):
    s = LocalStore(tmp_path)
    for key in ["src/p/foo/current", "src/p/foo/git/HEAD", "src/p/bar/current", "src/index.html"]:
        s.put(key, b"x")
    assert s.list("src/p/foo/") == ["src/p/foo/current", "src/p/foo/git/HEAD"]
    assert s.list("src/p/f") == ["src/p/foo/current", "src/p/foo/git/HEAD"]
    assert s.list_dirs("src/p/") == ["bar", "foo"]
    assert s.list_dirs("missing/") == []


def test_names_with_spaces_and_unicode(tmp_path):
    s = LocalStore(tmp_path)
    s.put("p/site/raw/my file #1 é.txt", b"x")
    assert s.list("p/site/raw/") == ["p/site/raw/my file #1 é.txt"]


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/."])
def test_rejects_bad_keys(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).put(key, b"x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.store'`.

- [ ] **Step 3: Implement**

`src/partlet/store.py`:

```python
"""Where published files go: a key/value interface over R2 or a local directory."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def list_dirs(self, prefix: str) -> list[str]: ...


def check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid store key {key!r}")
    return key


class LocalStore:
    """Stores each key as a file under `root`. Used for previews and tests."""

    def __init__(self, root: Path):
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*check_key(key).split("/"))

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        keys = (
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(".tmp-")
        )
        return sorted(k for k in keys if k.startswith(prefix))

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        base = self._path(prefix.rstrip("/"))
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/store.py tests/test_store.py
git commit -m "Add Store interface and local directory store"
```

---

### Task 5: Dumb-HTTP packs and pointers

**Files:**
- Create: `src/partlet/gitstatic.py`
- Test: `tests/test_gitstatic.py`

**Interfaces:**
- Consumes: `git_out` (Task 2), `Store`/`LocalStore` (Task 4), `export_project` and `helpers` in tests.
- Produces:
  - `MAX_PACKS = 20`
  - `@dataclass(frozen=True) class GitState(tip: str | None, packs: tuple[str, ...])` (pack names like `pack-<hash>`, no extension)
  - `@dataclass(frozen=True) class PackPlan(tip: str, packs: tuple[str, ...], superseded: tuple[str, ...])` (`superseded` are store keys no longer referenced after this publish)
  - `read_state(store: Store, git_prefix: str) -> GitState`
  - `upload_pack(store: Store, git_prefix: str, repo: Path, new_tip: str, old: GitState, workdir: Path, full: bool = False) -> PackPlan` (uploads pack files only)
  - `write_pointers(store: Store, git_prefix: str, plan: PackPlan) -> None` (writes `objects/info/packs`, `info/refs`, `HEAD`, in that order)

- [ ] **Step 1: Write the failing tests**

`tests/test_gitstatic.py`:

```python
from partlet import gitstatic
from partlet.export import export_project
from partlet.gitstatic import GitState, read_state, upload_pack, write_pointers
from partlet.gitutil import git, git_out
from partlet.manifest import Project
from partlet.store import LocalStore

PREFIX = "s/p/foo/git"


def publish(store, mono, tmp_path, n, full=False):
    repo = tmp_path / f"e{n}.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)
    plan = upload_pack(store, PREFIX, repo, tip, read_state(store, PREFIX), tmp_path / f"w{n}", full=full)
    write_pointers(store, PREFIX, plan)
    return tip, plan


def test_read_state_empty(tmp_path):
    assert read_state(LocalStore(tmp_path), PREFIX) == GitState(None, ())


def test_clone_then_pull_over_dumb_http(mono, tmp_path, serve):
    store = LocalStore(tmp_path / "out")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    tip1, plan1 = publish(store, mono, tmp_path, 1)
    assert read_state(store, PREFIX) == GitState(tip1, plan1.packs)
    assert store.get(f"{PREFIX}/HEAD") == b"ref: refs/heads/main\n"
    assert store.get(f"{PREFIX}/info/refs") == f"{tip1}\trefs/heads/main\n".encode()

    with serve(tmp_path / "out") as base:
        url = f"{base}/{PREFIX}"
        clone = tmp_path / "clone"
        git("clone", "-q", url, str(clone), cwd=tmp_path)
        assert (clone / "a.txt").read_text() == "one\n"

        mono.write("foo/a.txt", "one\ntwo\n")
        mono.commit("c2")
        tip2, plan2 = publish(store, mono, tmp_path, 2)
        assert len(plan2.packs) == 2
        assert plan2.packs[0] == plan1.packs[0]
        assert plan2.superseded == ()

        git("pull", "-q", "--ff-only", cwd=clone)
        assert git_out("rev-parse", "HEAD", cwd=clone) == tip2
        assert (clone / "a.txt").read_text() == "one\ntwo\n"


def test_consolidates_after_max_packs(mono, tmp_path, monkeypatch):
    monkeypatch.setattr(gitstatic, "MAX_PACKS", 2)
    store = LocalStore(tmp_path / "out")
    plans = []
    for n in range(3):
        mono.write("foo/a.txt", f"{n}\n")
        mono.commit(f"c{n}")
        plans.append(publish(store, mono, tmp_path, n)[1])
    assert len(plans[1].packs) == 2
    assert len(plans[2].packs) == 1
    assert set(plans[2].superseded) == {
        f"{PREFIX}/objects/pack/{p}.{ext}" for p in plans[1].packs for ext in ("pack", "idx")
    }


def test_full_pack_never_supersedes_itself(mono, tmp_path):
    store = LocalStore(tmp_path / "out")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    publish(store, mono, tmp_path, 1)
    _, again = publish(store, mono, tmp_path, 2, full=True)
    live = {f"{PREFIX}/objects/pack/{p}.{ext}" for p in again.packs for ext in ("pack", "idx")}
    assert not live & set(again.superseded)  # pack names can repeat; a live pack is never scheduled for deletion
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_gitstatic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.gitstatic'`.

- [ ] **Step 3: Implement**

`src/partlet/gitstatic.py`:

```python
"""Lay out a published repository for Git's dumb HTTP transport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import git_out
from partlet.store import Store

MAX_PACKS = 20


@dataclass(frozen=True)
class GitState:
    tip: str | None
    packs: tuple[str, ...]


@dataclass(frozen=True)
class PackPlan:
    tip: str
    packs: tuple[str, ...]
    superseded: tuple[str, ...]


def read_state(store: Store, git_prefix: str) -> GitState:
    tip = None
    refs = store.get(f"{git_prefix}/info/refs")
    for line in (refs or b"").decode("utf-8").splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main":
            tip = sha
    raw_packs = store.get(f"{git_prefix}/objects/info/packs")
    packs = tuple(
        line[2:].removesuffix(".pack")
        for line in (raw_packs or b"").decode("utf-8").splitlines()
        if line.startswith("P ")
    )
    return GitState(tip, packs)


def _pack_keys(git_prefix: str, pack: str) -> tuple[str, str]:
    base = f"{git_prefix}/objects/pack/{pack}"
    return f"{base}.pack", f"{base}.idx"


def upload_pack(
    store: Store,
    git_prefix: str,
    repo: Path,
    new_tip: str,
    old: GitState,
    workdir: Path,
    full: bool = False,
) -> PackPlan:
    """Upload one pack covering what `old` lacks; return the resulting pack list."""
    consolidate = full or old.tip is None or len(old.packs) >= MAX_PACKS
    workdir.mkdir(parents=True, exist_ok=True)
    revs = f"{new_tip}\n" + ("" if consolidate else f"^{old.tip}\n")
    digest = git_out(
        "pack-objects", "--revs", "--delta-base-offset", "-q", str(workdir / "pack"),
        cwd=repo, input=revs.encode(),
    )
    pack = f"pack-{digest}"
    for key, ext in zip(_pack_keys(git_prefix, pack), ("pack", "idx")):
        store.put(key, (workdir / f"{pack}.{ext}").read_bytes())

    packs = (pack,) if consolidate else (*old.packs, pack)
    dropped = [p for p in old.packs if p not in packs] if consolidate else []
    superseded = tuple(k for p in dropped for k in _pack_keys(git_prefix, p))
    return PackPlan(new_tip, packs, superseded)


def write_pointers(store: Store, git_prefix: str, plan: PackPlan) -> None:
    info_packs = "".join(f"P {p}.pack\n" for p in plan.packs) + "\n"
    store.put(f"{git_prefix}/objects/info/packs", info_packs.encode())
    store.put(f"{git_prefix}/info/refs", f"{plan.tip}\trefs/heads/main\n".encode())
    store.put(f"{git_prefix}/HEAD", b"ref: refs/heads/main\n")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_gitstatic.py -v`
Expected: all PASS. The clone test runs real `git clone` and `git pull` against `http.server`, which returns `info/refs` as a plain file, so git uses the dumb protocol.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/gitstatic.py tests/test_gitstatic.py
git commit -m "Write incremental packs and dumb-HTTP pointers"
```

---

### Task 6: Site content helpers (tree, URLs, links, Markdown, highlighting)

**Files:**
- Create: `src/partlet/site/__init__.py`, `src/partlet/site/tree.py`, `src/partlet/site/urls.py`, `src/partlet/site/links.py`, `src/partlet/site/markdown.py`, `src/partlet/site/highlight.py`
- Test: `tests/test_site_content.py`

**Interfaces:**
- Consumes: `git` (Task 2).
- Produces:
  - `SIZE_CAP = 1024 * 1024`
  - `@dataclass(frozen=True) class FileEntry(path: str, data: bytes, is_symlink: bool = False)` with properties `name: str`, `parent: str` (`""` at root), `size: int`
  - `read_tree(repo: Path, tip: str) -> list[FileEntry]` (sorted by path; submodules skipped; symlink `data` is the link target)
  - `is_binary(data: bytes) -> bool`, `is_viewable(entry: FileEntry) -> bool`
  - `urls.tree_url(project: str, directory: str) -> str`, `urls.blob_url(project, path) -> str`, `urls.raw_url(project, path) -> str`, `urls.archive_url(project, fmt) -> str`
  - `class Linker(project: str, files: set[str], dirs: set[str])` with `resolve(base_dir: str, href: str, raw: bool = False) -> str`
  - `render_markdown(text: str, base_dir: str, linker: Linker) -> str`
  - `highlight_file(path: str, text: str) -> str`, `pygments_css() -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_site_content.py`:

```python
from partlet.export import export_project
from partlet.manifest import Project
from partlet.site import urls
from partlet.site.highlight import highlight_file, pygments_css
from partlet.site.links import Linker
from partlet.site.markdown import render_markdown
from partlet.site.tree import SIZE_CAP, FileEntry, is_binary, is_viewable, read_tree


def test_read_tree_reads_files_and_symlinks(mono, tmp_path):
    mono.write("foo/a.txt", "alpha\n")
    mono.write("foo/sub/b.bin", b"\x00\x01")
    mono.symlink("foo/link", "../../etc/passwd")
    mono.commit("c1")
    repo = tmp_path / "e.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)
    entries = read_tree(repo, tip)
    assert [e.path for e in entries] == ["a.txt", "link", "sub/b.bin"]
    assert entries[0].data == b"alpha\n" and not entries[0].is_symlink
    assert entries[1].is_symlink and entries[1].data == b"../../etc/passwd"
    assert entries[2].parent == "sub" and entries[2].name == "b.bin"


def test_binary_and_viewable():
    assert is_binary(b"a\x00b")
    assert is_binary(b"\xff\xfe\xfa")
    assert not is_binary("héllo".encode())
    assert is_viewable(FileEntry("a.txt", b"hi"))
    assert not is_viewable(FileEntry("a.txt", b"x" * (SIZE_CAP + 1)))
    assert not is_viewable(FileEntry("a.bin", b"\x00"))
    assert not is_viewable(FileEntry("l", b"target", is_symlink=True))


def test_urls_percent_encode():
    assert urls.tree_url("foo", "") == "/foo"
    assert urls.tree_url("foo", "a b") == "/foo/tree/a%20b"
    assert urls.blob_url("foo", "dir/#1?é.txt") == "/foo/blob/dir/%231%3F%C3%A9.txt"
    assert urls.raw_url("foo", "100%.txt") == "/foo/raw/100%25.txt"
    assert urls.archive_url("foo", "tar.gz") == "/foo/archive/foo.tar.gz"


def make_linker():
    return Linker("foo", files={"README.md", "docs/x.md", "docs/img.png", "y.txt"}, dirs={"", "docs", "docs/sub"})


def test_linker_resolves_relative_links():
    link = make_linker()
    assert link.resolve("", "docs/x.md") == "/foo/blob/docs/x.md"
    assert link.resolve("docs", "../y.txt") == "/foo/blob/y.txt"
    assert link.resolve("docs", "sub/") == "/foo/tree/docs/sub"
    assert link.resolve("docs", "sub") == "/foo/tree/docs/sub"
    assert link.resolve("docs", "..") == "/foo"
    assert link.resolve("docs", "img.png", raw=True) == "/foo/raw/docs/img.png"
    assert link.resolve("", "docs/x.md#part") == "/foo/blob/docs/x.md#part"


def test_linker_leaves_other_links_alone():
    link = make_linker()
    for href in ["https://example.com/x", "mailto:a@b", "#anchor", "/abs/path", "../../outside", ""]:
        assert link.resolve("docs", href) == href


def test_markdown_escapes_raw_html():
    html = render_markdown("hi <script>alert(1)</script>\n\n<b>x</b>\n", "", make_linker())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>" not in html


def test_markdown_rewrites_links_and_images():
    # Adjacent literals keep "](" out of this file, which docket's link checker would flag.
    html = render_markdown("[x]" "(x.md) ![i]" "(img.png) [ext](https://e.com)\n", "docs", make_linker())
    assert 'href="/foo/blob/docs/x.md"' in html
    assert 'src="/foo/raw/docs/img.png"' in html
    assert 'href="https://e.com"' in html


def test_markdown_drops_javascript_links():
    html = render_markdown("[x]" "(javascript:alert(1))\n", "", make_linker())
    assert 'href="javascript' not in html


def test_markdown_tables():
    html = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n", "", make_linker())
    assert "<table>" in html


def test_highlight():
    html = highlight_file("x.py", "def f():\n    return 1\n")
    assert 'class="hl' in html and "def" in html
    assert highlight_file("unknown.zzz", "<b>").count("&lt;b&gt;") == 1
    assert ".hl" in pygments_css()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_site_content.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.site'`.

- [ ] **Step 3: Implement**

`src/partlet/site/__init__.py`:

```python
"""Static site rendering for published projects."""
```

`src/partlet/site/tree.py`:

```python
"""Read the files of an export tip."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import git

SIZE_CAP = 1024 * 1024
SYMLINK_MODE = b"120000"


@dataclass(frozen=True)
class FileEntry:
    path: str
    data: bytes
    is_symlink: bool = False

    @property
    def name(self) -> str:
        return posixpath.basename(self.path)

    @property
    def parent(self) -> str:
        return posixpath.dirname(self.path)

    @property
    def size(self) -> int:
        return len(self.data)


def read_tree(repo: Path, tip: str) -> list[FileEntry]:
    listing = git("ls-tree", "-r", "-z", "--full-tree", tip, cwd=repo).stdout
    items: list[tuple[bytes, str, str]] = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, raw_path = record.split(b"\t", 1)
        mode, kind, sha = meta.split()
        if kind != b"blob":
            continue  # submodules (gitlinks) have no content here
        items.append((mode, sha.decode(), raw_path.decode("utf-8", "replace")))
    if not items:
        return []

    batch = git("cat-file", "--batch", cwd=repo, input="".join(f"{s}\n" for _, s, _ in items).encode()).stdout
    entries = []
    pos = 0
    for mode, _sha, path in items:
        newline = batch.index(b"\n", pos)
        size = int(batch[pos:newline].split()[2])
        start = newline + 1
        entries.append(FileEntry(path, batch[start : start + size], mode == SYMLINK_MODE))
        pos = start + size + 1  # content is followed by a newline
    return sorted(entries, key=lambda e: e.path)


def is_binary(data: bytes) -> bool:
    if b"\0" in data[:8000]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def is_viewable(entry: FileEntry) -> bool:
    return not entry.is_symlink and entry.size <= SIZE_CAP and not is_binary(entry.data)
```

`src/partlet/site/urls.py`:

```python
"""Root-relative URLs for project pages, served by the Worker."""

from urllib.parse import quote


def tree_url(project: str, directory: str) -> str:
    return f"/{project}" if not directory else f"/{project}/tree/{quote(directory)}"


def blob_url(project: str, path: str) -> str:
    return f"/{project}/blob/{quote(path)}"


def raw_url(project: str, path: str) -> str:
    return f"/{project}/raw/{quote(path)}"


def archive_url(project: str, fmt: str) -> str:
    return f"/{project}/archive/{project}.{fmt}"
```

`src/partlet/site/links.py`:

```python
"""Rewrite relative links in rendered Markdown to project URLs."""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit

from partlet.site import urls


class Linker:
    def __init__(self, project: str, files: set[str], dirs: set[str]):
        self.project = project
        self.files = files
        self.dirs = dirs

    def resolve(self, base_dir: str, href: str, raw: bool = False) -> str:
        if not href or href.startswith(("/", "#")):
            return href
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            return href
        target = posixpath.normpath(posixpath.join(base_dir, unquote(parts.path)))
        if target == ".":
            target = ""
        if target == ".." or target.startswith("../"):
            return href
        if raw:
            url = urls.raw_url(self.project, target)
        elif target in self.dirs:
            url = urls.tree_url(self.project, target)
        else:
            url = urls.blob_url(self.project, target)
        if parts.query:
            url += f"?{parts.query}"
        if parts.fragment:
            url += f"#{parts.fragment}"
        return url
```

`src/partlet/site/markdown.py`:

```python
"""Render README Markdown safely."""

from __future__ import annotations

from collections.abc import Iterator

from markdown_it import MarkdownIt
from markdown_it.token import Token

from partlet.site.links import Linker


def _parser() -> MarkdownIt:
    # html=False escapes raw HTML; markdown-it's link validation drops javascript: URLs.
    return MarkdownIt("commonmark", {"html": False}).enable(["table", "strikethrough"])


def _walk(tokens: list[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token
        if token.children:
            yield from _walk(token.children)


def render_markdown(text: str, base_dir: str, linker: Linker) -> str:
    md = _parser()
    tokens = md.parse(text)
    for token in _walk(tokens):
        if token.type == "link_open":
            token.attrSet("href", linker.resolve(base_dir, str(token.attrGet("href") or "")))
        elif token.type == "image":
            token.attrSet("src", linker.resolve(base_dir, str(token.attrGet("src") or ""), raw=True))
    return md.renderer.render(tokens, md.options, {})
```

`src/partlet/site/highlight.py`:

```python
"""Syntax highlighting for file pages."""

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_for_filename
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(linenos="table", lineanchors="L", anchorlinenos=True, cssclass="hl")


def highlight_file(path: str, text: str) -> str:
    try:
        lexer = get_lexer_for_filename(path, text, stripnl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False)
    return highlight(text, lexer, _FORMATTER)


def pygments_css() -> str:
    return _FORMATTER.get_style_defs(".hl")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_site_content.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/site tests/test_site_content.py
git commit -m "Add tree reading, link rewriting, Markdown and highlighting"
```

---

### Task 7: Page rendering and templates

**Files:**
- Create: `src/partlet/site/render.py`, `src/partlet/site/style.css`, `src/partlet/site/templates/base.html`, `src/partlet/site/templates/tree.html`, `src/partlet/site/templates/blob.html`, `src/partlet/site/templates/index.html`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: everything in Task 6.
- Produces:
  - `@dataclass(frozen=True) class ProjectInfo(name: str, description: str, tip: str, base_url: str, updated: str)`
  - `render_project(info: ProjectInfo, entries: list[FileEntry]) -> dict[str, bytes]` with keys `index.html`, `tree/<dir>/index.html`, `blob/<path>`, `raw/<path>`
  - `render_site_index(base_url: str, projects: list[dict]) -> bytes` (each dict has `name`, `description`, `tip`, `updated`)
  - `site_stylesheet() -> bytes`

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:

```python
from partlet.site.render import ProjectInfo, render_project, render_site_index, site_stylesheet
from partlet.site.tree import SIZE_CAP, FileEntry

INFO = ProjectInfo("foo", "Foo tool", "a" * 40, "https://partlet.example", "2026-01-01T00:00:00+00:00")


def render(entries):
    return {k: v.decode("utf-8") if not k.startswith("raw/") else v for k, v in render_project(INFO, entries).items()}


def test_keys_for_every_file_and_directory():
    pages = render([
        FileEntry("README.md", b"# Hello\n"),
        FileEntry("src/main.py", b"print(1)\n"),
        FileEntry("src/deep/x.txt", b"x\n"),
    ])
    assert set(pages) == {
        "index.html",
        "tree/src/index.html",
        "tree/src/deep/index.html",
        "blob/README.md",
        "blob/src/main.py",
        "blob/src/deep/x.txt",
        "raw/README.md",
        "raw/src/main.py",
        "raw/src/deep/x.txt",
    }
    assert pages["raw/src/main.py"] == b"print(1)\n"


def test_project_page_has_readme_clone_url_and_downloads():
    page = render([FileEntry("README.md", b"# Hello\n"), FileEntry("a.txt", b"a")])["index.html"]
    assert "<h1>Hello</h1>" in page
    assert "git clone https://partlet.example/foo" in page
    assert 'href="/foo/archive/foo.tar.gz"' in page
    assert 'href="/foo/archive/foo.zip"' in page
    assert 'href="/foo/blob/a.txt"' in page
    assert "Foo tool" in page
    assert 'href="/_partlet/style.css"' in page
    assert "<script" not in page


def test_subdirectory_readme_links_resolve_from_that_directory():
    pages = render([FileEntry("docs/README.md", b"[up]" b"(../a.txt)\n"), FileEntry("a.txt", b"a")])
    assert 'href="/foo/blob/a.txt"' in pages["tree/docs/index.html"]


def test_file_page_highlights_and_links_raw():
    page = render([FileEntry("src/main.py", b"def f(): pass\n")])["blob/src/main.py"]
    assert 'class="hl' in page
    assert 'href="/foo/raw/src/main.py"' in page
    assert 'href="/foo/tree/src"' in page  # breadcrumb


def test_binary_and_large_files_get_download_only():
    pages = render([FileEntry("a.bin", b"\x00\x01"), FileEntry("big.txt", b"x" * (SIZE_CAP + 1))])
    for key in ("blob/a.bin", "blob/big.txt"):
        assert 'class="hl' not in pages[key]
        assert "raw" in pages[key] and "not shown" in pages[key]


def test_special_file_names_are_encoded():
    pages = render([FileEntry("my dir/#1 ?é%.txt", b"x\n")])
    assert "blob/my dir/#1 ?é%.txt" in pages
    assert "raw/my dir/#1 ?é%.txt" in pages
    assert 'href="/foo/tree/my%20dir"' in pages["index.html"]
    assert 'href="/foo/blob/my%20dir/%231%20%3F%C3%A9%25.txt"' in pages["tree/my dir/index.html"]
    assert "#1 ?é%.txt" in pages["tree/my dir/index.html"]  # visible label unencoded


def test_symlinks_are_shown_not_followed():
    pages = render([FileEntry("link", b"../../etc/passwd", is_symlink=True)])
    assert "Symbolic link to" in pages["blob/link"]
    assert "../../etc/passwd" in pages["blob/link"]
    assert pages["raw/link"] == b"../../etc/passwd"


def test_html_in_names_and_content_is_escaped():
    pages = render([FileEntry("<b>.txt", b"<script>x</script>\n")])
    assert "<b>.txt" not in pages["index.html"]
    assert "<script>x" not in pages["blob/<b>.txt"]


def test_site_index_lists_projects():
    page = render_site_index("https://partlet.example", [
        {"name": "foo", "description": "Foo tool", "tip": "a" * 40, "updated": "2026-01-01T00:00:00+00:00"},
    ]).decode()
    assert 'href="/foo"' in page and "Foo tool" in page


def test_stylesheet_includes_pygments():
    assert b".hl" in site_stylesheet()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.site.render'`.

- [ ] **Step 3: Write the templates and stylesheet**

`src/partlet/site/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{% block title %}{% endblock %}</title>
<link rel="stylesheet" href="/_partlet/style.css">
</head>
<body>
<header class="top"><a href="/">Partlet</a></header>
<main>
{% block main %}{% endblock %}
</main>
</body>
</html>
```

`src/partlet/site/templates/tree.html`:

```html
{% extends "base.html" %}
{% block title %}{{ project.name }}{% if directory %}/{{ directory }}{% endif %}{% endblock %}
{% block main %}
<nav class="crumbs">{% for label, url in crumbs %}<a href="{{ url }}">{{ label }}</a>{% if not loop.last %} / {% endif %}{% endfor %}</nav>
{% if not directory %}
<section class="project">
  {% if project.description %}<p class="description">{{ project.description }}</p>{% endif %}
  <pre class="clone">git clone {{ clone_url }}</pre>
  <p class="downloads">Download: {% for fmt, url in archives %}<a href="{{ url }}">{{ fmt }}</a>{% if not loop.last %} · {% endif %}{% endfor %}</p>
  <p class="tip">Commit <code>{{ project.tip[:12] }}</code>, updated {{ project.updated }}</p>
</section>
{% endif %}
<table class="listing">
{% for name, url in subdirs %}<tr><td class="dir"><a href="{{ url }}">{{ name }}/</a></td><td></td></tr>
{% endfor %}{% for name, url, size in files %}<tr><td class="file"><a href="{{ url }}">{{ name }}</a></td><td class="size">{{ size }}</td></tr>
{% endfor %}
</table>
{% if readme_html %}<article class="readme">{{ readme_html | safe }}</article>{% endif %}
{% endblock %}
```

`src/partlet/site/templates/blob.html`:

```html
{% extends "base.html" %}
{% block title %}{{ project.name }}/{{ path }}{% endblock %}
{% block main %}
<nav class="crumbs">{% for label, url in crumbs %}<a href="{{ url }}">{{ label }}</a> / {% endfor %}{{ name }}</nav>
<p class="fileinfo">{{ size }} · <a href="{{ raw_url }}">raw</a></p>
{% if symlink_target is not none %}
<p>Symbolic link to <code>{{ symlink_target }}</code></p>
{% elif body_html %}
{{ body_html | safe }}
{% else %}
<p>This file is binary or too large and is not shown. <a href="{{ raw_url }}">Download the raw file</a>.</p>
{% endif %}
{% endblock %}
```

`src/partlet/site/templates/index.html`:

```html
{% extends "base.html" %}
{% block title %}Projects{% endblock %}
{% block main %}
<h1>Projects</h1>
<table class="listing">
{% for p in projects %}<tr><td><a href="/{{ p.name }}">{{ p.name }}</a></td><td>{{ p.description }}</td><td class="size">{{ p.updated }}</td></tr>
{% endfor %}
</table>
{% endblock %}
```

`src/partlet/site/style.css`:

```css
:root { --fg: #1f2328; --muted: #59636e; --bg: #ffffff; --line: #d1d9e0; --link: #0969da; --code-bg: #f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6edf3; --muted: #9198a1; --bg: #0d1117; --line: #30363d; --link: #4493f8; --code-bg: #161b22; }
}
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
a { color: var(--link); text-decoration: none; }
a:hover { text-decoration: underline; }
header.top { padding: 10px 16px; border-bottom: 1px solid var(--line); font-weight: 600; }
main { max-width: 980px; margin: 0 auto; padding: 16px; }
.crumbs { font-size: 18px; margin-bottom: 12px; overflow-wrap: anywhere; }
.description, .tip, .fileinfo { color: var(--muted); }
pre, code { font: 13px/1.45 ui-monospace, monospace; }
pre.clone { background: var(--code-bg); padding: 8px 12px; border-radius: 6px; overflow-x: auto; }
table.listing { width: 100%; border-collapse: collapse; margin: 12px 0; }
table.listing td { padding: 6px 8px; border-top: 1px solid var(--line); overflow-wrap: anywhere; }
td.size { color: var(--muted); text-align: right; white-space: nowrap; }
article.readme { border-top: 1px solid var(--line); margin-top: 16px; padding-top: 8px; }
article.readme pre { background: var(--code-bg); padding: 12px; overflow-x: auto; }
.hl { overflow-x: auto; background: var(--code-bg); border-radius: 6px; }
.hl table { border-collapse: collapse; }
.hl pre { margin: 0; padding: 8px; }
.hl .linenos { color: var(--muted); user-select: none; }
```

- [ ] **Step 4: Implement the renderer**

`src/partlet/site/render.py`:

```python
"""Turn an export tip into static pages."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from importlib import resources

from jinja2 import Environment, PackageLoader, select_autoescape

from partlet.archive import ARCHIVE_FORMATS
from partlet.site import urls
from partlet.site.highlight import highlight_file, pygments_css
from partlet.site.links import Linker
from partlet.site.markdown import render_markdown
from partlet.site.tree import FileEntry, is_viewable

README_NAMES = ("readme.md", "readme.markdown", "readme", "readme.txt", "readme.rst")
MARKDOWN_SUFFIXES = (".md", ".markdown")

_env = Environment(
    loader=PackageLoader("partlet.site", "templates"),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


@dataclass(frozen=True)
class ProjectInfo:
    name: str
    description: str
    tip: str
    base_url: str
    updated: str


def _human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB"):
        if n < 1024 or unit == "MiB":
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


def _directories(entries: list[FileEntry]) -> dict[str, tuple[set[str], list[FileEntry]]]:
    dirs: dict[str, tuple[set[str], list[FileEntry]]] = {"": (set(), [])}
    for entry in entries:
        parent = entry.parent
        dirs.setdefault(parent, (set(), []))[1].append(entry)
        while parent:
            grandparent = posixpath.dirname(parent)
            dirs.setdefault(grandparent, (set(), []))[0].add(parent)
            dirs.setdefault(parent, (set(), []))
            parent = grandparent
    return dirs


def _crumbs(project: str, directory: str) -> list[tuple[str, str]]:
    crumbs = [(project, urls.tree_url(project, ""))]
    if directory:
        parts = directory.split("/")
        for i, part in enumerate(parts):
            crumbs.append((part, urls.tree_url(project, "/".join(parts[: i + 1]))))
    return crumbs


def _readme_html(files: list[FileEntry], directory: str, linker: Linker) -> str | None:
    by_name = {f.name.lower(): f for f in files if is_viewable(f)}
    for candidate in README_NAMES:
        entry = by_name.get(candidate)
        if entry is None:
            continue
        text = entry.data.decode("utf-8")
        if entry.name.lower().endswith(MARKDOWN_SUFFIXES):
            return render_markdown(text, directory, linker)
        return _env.from_string("<pre>{{ text }}</pre>").render(text=text)
    return None


def render_project(info: ProjectInfo, entries: list[FileEntry]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    dirs = _directories(entries)
    linker = Linker(info.name, {e.path for e in entries}, set(dirs))
    tree_tpl = _env.get_template("tree.html")
    blob_tpl = _env.get_template("blob.html")
    archives = [(fmt, urls.archive_url(info.name, fmt)) for fmt in ARCHIVE_FORMATS]

    for directory, (subdirs, files) in dirs.items():
        html = tree_tpl.render(
            project=info,
            directory=directory,
            crumbs=_crumbs(info.name, directory),
            clone_url=f"{info.base_url}/{info.name}",
            archives=archives,
            subdirs=[(posixpath.basename(d), urls.tree_url(info.name, d)) for d in sorted(subdirs)],
            files=[(f.name, urls.blob_url(info.name, f.path), _human_size(f.size)) for f in sorted(files, key=lambda f: f.name)],
            readme_html=_readme_html(files, directory, linker),
        )
        key = "index.html" if not directory else f"tree/{directory}/index.html"
        out[key] = html.encode("utf-8")

    for entry in entries:
        body = highlight_file(entry.path, entry.data.decode("utf-8")) if is_viewable(entry) else None
        html = blob_tpl.render(
            project=info,
            path=entry.path,
            name=entry.name,
            crumbs=_crumbs(info.name, entry.parent),
            size=_human_size(entry.size),
            raw_url=urls.raw_url(info.name, entry.path),
            symlink_target=entry.data.decode("utf-8", "replace") if entry.is_symlink else None,
            body_html=body,
        )
        out[f"blob/{entry.path}"] = html.encode("utf-8")
        out[f"raw/{entry.path}"] = entry.data
    return out


def render_site_index(base_url: str, projects: list[dict]) -> bytes:
    ordered = sorted(projects, key=lambda p: p["name"])
    return _env.get_template("index.html").render(base_url=base_url, projects=ordered).encode("utf-8")


def site_stylesheet() -> bytes:
    base = resources.files("partlet.site").joinpath("style.css").read_text(encoding="utf-8")
    return (base + "\n" + pygments_css() + "\n").encode("utf-8")
```

Note: `render.py` imports `ARCHIVE_FORMATS` from `partlet.archive`, which Task 8 creates. To keep this task self-contained, create `src/partlet/archive.py` now with only the constant, and Task 8 adds the function:

```python
"""Downloadable archives of an export tip."""

ARCHIVE_FORMATS = ("tar.gz", "zip")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_render.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/partlet/site src/partlet/archive.py tests/test_render.py
git commit -m "Render project pages, file views and site index"
```

---

### Task 8: Archives

**Files:**
- Modify: `src/partlet/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `git` (Task 2), `ARCHIVE_FORMATS` (Task 7).
- Produces: `make_archives(repo: Path, name: str, tip: str) -> dict[str, bytes]`, keyed by format (`"tar.gz"`, `"zip"`).

- [ ] **Step 1: Write the failing test**

`tests/test_archive.py`:

```python
import io
import tarfile
import zipfile

from partlet.archive import make_archives
from partlet.export import export_project
from partlet.manifest import Project


def test_archives_contain_prefixed_files_and_are_deterministic(mono, tmp_path):
    mono.write("foo/a.txt", "alpha\n")
    mono.write("foo/sub/b.txt", "beta\n")
    mono.commit("c1")
    repo = tmp_path / "e.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)

    first = make_archives(repo, "foo", tip)
    second = make_archives(repo, "foo", tip)
    assert first == second
    assert set(first) == {"tar.gz", "zip"}

    with tarfile.open(fileobj=io.BytesIO(first["tar.gz"]), mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
    assert names == ["foo/a.txt", "foo/sub/b.txt"]

    with zipfile.ZipFile(io.BytesIO(first["zip"])) as z:
        assert z.read("foo/a.txt") == b"alpha\n"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: FAIL with `ImportError: cannot import name 'make_archives'`.

- [ ] **Step 3: Implement**

Replace `src/partlet/archive.py` with:

```python
"""Downloadable archives of an export tip."""

from __future__ import annotations

from pathlib import Path

from partlet.gitutil import git

ARCHIVE_FORMATS = ("tar.gz", "zip")


def make_archives(repo: Path, name: str, tip: str) -> dict[str, bytes]:
    return {
        fmt: git("archive", f"--format={fmt}", f"--prefix={name}/", tip, cwd=repo).stdout
        for fmt in ARCHIVE_FORMATS
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/archive.py tests/test_archive.py
git commit -m "Build tar.gz and zip archives of the export tip"
```

---

### Task 9: Publish pipeline, cleanup, site index, and `partlet build`

**Files:**
- Create: `src/partlet/publish.py`, `src/partlet/cli.py`
- Test: `tests/test_publish.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass(frozen=True) class ProjectResult(name: str, status: Literal["published", "unchanged", "skipped", "failed"], tip: str | None = None, reason: str = "")`
  - `project_prefix(source: str, name: str) -> str` (`"<source>/p/<name>"`)
  - `build_id(tip: str, description: str) -> str` (16 hex chars)
  - `publish_project(monorepo: Path, manifest: Manifest, project: Project, store: Store, workdir: Path) -> ProjectResult`
  - `publish_all(monorepo: Path, manifest: Manifest, store: Store, workdir: Path) -> list[ProjectResult]`
  - `write_site_index(store: Store, site: Site) -> None`
  - `cli.main(argv: list[str] | None = None) -> int` with subcommand `build --repo DIR --manifest FILE --out DIR`

- [ ] **Step 1: Write the failing pipeline tests**

`tests/test_publish.py`:

```python
import json

import pytest

from partlet.gitutil import git
from partlet.manifest import parse_manifest
from partlet.publish import build_id, publish_all
from partlet.store import LocalStore


def manifest(approved, extra=""):
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
description = "Foo tool"
approved = "{approved}"
{extra}

[projects.unapproved]
path = "foo"
""")


def export_tip(mono, tmp_path):
    """The tip `partlet review` would show: export once and read it."""
    from partlet.export import export_project
    from partlet.manifest import Project

    dest = tmp_path / f"probe-{len(list(tmp_path.glob('probe-*')))}.git"
    return export_project(mono.path, "main", Project("foo", "foo"), dest)


def run(mono, tmp_path, store, approved, extra=""):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    return {r.name: r for r in publish_all(mono.path, manifest(approved, extra), store, work)}


@pytest.fixture
def first(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    return store, approved


def test_first_publish_writes_everything(mono, tmp_path, first):
    store, approved = first
    results = run(mono, tmp_path, store, approved)
    assert results["foo"].status == "published"
    assert results["unapproved"].status == "skipped"

    current = json.loads(store.get("s/p/foo/current"))
    assert current["tip"] == approved
    assert current["build"] == build_id(approved, "Foo tool")
    assert current["description"] == "Foo tool"
    build = current["build"]
    assert store.get(f"s/p/foo/site/{build}/index.html") is not None
    assert store.get(f"s/p/foo/site/{build}/raw/a.txt") == b"one\n"
    assert store.get(f"s/p/foo/archive/{approved}.tar.gz") is not None
    assert store.get(f"s/p/foo/archive/{approved}.zip") is not None
    assert store.get("s/p/foo/git/info/refs") == f"{approved}\trefs/heads/main\n".encode()

    index = json.loads(store.get("s/index.json"))
    assert [p["name"] for p in index] == ["foo"]
    assert b'href="/foo"' in store.get("s/index.html")
    assert b".hl" in store.get("s/static/style.css")


def test_second_run_without_changes_is_unchanged(mono, tmp_path, first, serve):
    store, approved = first
    run(mono, tmp_path, store, approved)
    packs_before = store.list("s/p/foo/git/objects/pack/")
    results = run(mono, tmp_path, store, approved)
    assert results["foo"].status == "unchanged"
    assert store.list("s/p/foo/git/objects/pack/") == packs_before
    with serve(tmp_path / "out") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "a.txt").read_text() == "one\n"


def test_new_commits_publish_and_old_build_is_cleaned_up_one_publish_later(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    build1 = json.loads(store.get("s/p/foo/current"))["build"]

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    assert run(mono, tmp_path, store, approved)["foo"].status == "published"
    build2 = json.loads(store.get("s/p/foo/current"))["build"]
    assert build2 != build1
    assert store.list(f"s/p/foo/site/{build1}/")  # still present: one publish of grace
    assert f"s/p/foo/site/{build1}/index.html" in json.loads(store.get("s/p/foo/cleanup.json"))

    mono.write("foo/a.txt", "one\ntwo\nthree\n")
    mono.commit("c3")
    run(mono, tmp_path, store, approved)
    assert store.list(f"s/p/foo/site/{build1}/") == []
    assert store.list(f"s/p/foo/site/{build2}/")


def test_description_change_rerenders_without_new_pack(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    packs = store.list("s/p/foo/git/objects/pack/")
    changed = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"
[projects.foo]
path = "foo"
description = "New words"
approved = "{approved}"
""")
    results = {r.name: r for r in publish_all(mono.path, changed, store, tmp_path / "w-desc")}
    assert results["foo"].status == "published"
    assert store.list("s/p/foo/git/objects/pack/") == packs
    assert json.loads(store.get("s/p/foo/current"))["description"] == "New words"


def test_rewrite_is_rejected_and_nothing_changes(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    before = store.get("s/p/foo/git/info/refs")
    git("commit", "-q", "--amend", "-m", "rewritten", cwd=mono.path,
        env={"GIT_COMMITTER_DATE": "1767229200 +0000", "GIT_AUTHOR_DATE": "1767229200 +0000"})
    new_approved = export_tip(mono, tmp_path)
    result = run(mono, tmp_path, store, new_approved)["foo"]
    assert result.status == "failed" and "rewrite" in result.reason
    assert store.get("s/p/foo/git/info/refs") == before


def test_allowed_rewrite_publishes_full_pack(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    old_tip = approved
    git("commit", "-q", "--amend", "-m", "rewritten", cwd=mono.path,
        env={"GIT_COMMITTER_DATE": "1767229200 +0000", "GIT_AUTHOR_DATE": "1767229200 +0000"})
    new_tip = export_tip(mono, tmp_path)
    result = run(mono, tmp_path, store, new_tip, extra=f'allow_rewrite_of = "{old_tip}"')["foo"]
    assert result.status == "published"
    packs = store.get("s/p/foo/git/objects/info/packs").decode().split()
    assert packs.count("P") == 1


def test_missing_directory_fails_project_but_index_still_written(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    mono.mv("foo", "bar")
    mono.commit("move without manifest update")
    result = run(mono, tmp_path, store, approved)["foo"]
    assert result.status == "failed" and "previous_paths" in result.reason
    assert store.get("s/index.json") is not None
    assert json.loads(store.get("s/p/foo/current"))["tip"] == approved
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_publish.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.publish'`.

- [ ] **Step 3: Implement the pipeline**

`src/partlet/publish.py`:

```python
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
from partlet.site.render import ProjectInfo, render_project, render_site_index, site_stylesheet
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


def build_id(tip: str, description: str) -> str:
    digest = hashlib.sha256(f"{tip}\0{description}\0{__version__}".encode("utf-8"))
    return digest.hexdigest()[:16]


def _read_json(store: Store, key: str):
    raw = store.get(key)
    return None if raw is None else json.loads(raw)


def _put_json(store: Store, key: str, value) -> None:
    store.put(key, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"), "application/json")


def _run_cleanup(store: Store, prefix: str) -> None:
    for key in _read_json(store, f"{prefix}/cleanup.json") or []:
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
    try:
        mailmap = monorepo / site.mailmap if site.mailmap else None
        repo = pdir / "export.git"
        tip = export_project(monorepo, site.branch, project, repo, mailmap)

        state = read_state(store, f"{prefix}/git")
        decision = check_history(repo, tip, state.tip, project.approved, project.allow_rewrite_of)
        current = _read_json(store, f"{prefix}/current")
        build = build_id(tip, project.description)
        if decision.action == "unchanged" and current and current.get("build") == build:
            return ProjectResult(project.name, "unchanged", tip, decision.reason)

        _run_cleanup(store, prefix)
        superseded: list[str] = []

        # 1. New objects first: nothing references them yet.
        plan = None
        if decision.action != "unchanged":
            plan = upload_pack(
                store, f"{prefix}/git", repo, tip, state, pdir / "packs",
                full=decision.action == "rewrite",
            )
            superseded += plan.superseded

        updated = git_out("show", "-s", "--format=%cI", tip, cwd=repo)
        info = ProjectInfo(project.name, project.description, tip, site.base_url, updated)
        for key, data in render_project(info, read_tree(repo, tip)).items():
            store.put(f"{prefix}/site/{build}/{key}", data)
        for fmt, data in make_archives(repo, project.name, tip).items():
            store.put(f"{prefix}/archive/{tip}.{fmt}", data)

        # 2. Pointers, so refs never name objects that are not uploaded yet.
        if plan is not None:
            write_pointers(store, f"{prefix}/git", plan)
        _put_json(store, f"{prefix}/current", {
            "name": project.name,
            "description": project.description,
            "tip": tip,
            "build": build,
            "updated": updated,
        })

        # 3. Record what is now unreferenced; the next publish deletes it.
        if current:
            if current.get("build") != build:
                superseded += store.list(f"{prefix}/site/{current['build']}/")
            if current.get("tip") != tip:
                superseded += [f"{prefix}/archive/{current['tip']}.{fmt}" for fmt in ARCHIVE_FORMATS]
        _put_json(store, f"{prefix}/cleanup.json", sorted(set(superseded)))
        return ProjectResult(project.name, "published", tip, decision.reason)
    except (ExportError, HistoryError, GitError) as e:
        return ProjectResult(project.name, "failed", reason=str(e))


def write_site_index(store: Store, site: Site) -> None:
    projects = []
    for name in store.list_dirs(f"{site.source}/p/"):
        current = _read_json(store, f"{project_prefix(site.source, name)}/current")
        if current:
            projects.append({k: current[k] for k in ("name", "description", "tip", "updated")})
    projects.sort(key=lambda p: p["name"])
    _put_json(store, f"{site.source}/index.json", projects)
    store.put(f"{site.source}/index.html", render_site_index(site.base_url, projects), "text/html; charset=utf-8")
    store.put(f"{site.source}/static/style.css", site_stylesheet(), "text/css; charset=utf-8")


def publish_all(monorepo: Path, manifest: Manifest, store: Store, workdir: Path) -> list[ProjectResult]:
    results = [
        publish_project(monorepo, manifest, project, store, workdir)
        for project in manifest.projects.values()
    ]
    write_site_index(store, manifest.site)
    return results
```

Content types on `put` are ignored by `LocalStore`; the R2 store in plan 3 uses them. Site pages and raw files are stored without a type here; the Worker assigns types on the way out (plan 2).

- [ ] **Step 4: Run the pipeline tests to verify they pass**

Run: `.venv/bin/pytest tests/test_publish.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing CLI test**

`tests/test_cli.py`:

```python
from partlet.cli import main
from partlet.export import export_project
from partlet.gitutil import git
from partlet.manifest import Project


def test_build_end_to_end_and_clone(mono, tmp_path, serve, capsys):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    tip = export_project(mono.path, "main", Project("foo", "foo"), tmp_path / "probe.git")
    mono.write("partlet.toml", f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{tip}"
""")
    mono.commit("add manifest")  # does not touch foo/, so the export tip is unchanged

    out = tmp_path / "out"
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert "foo" in capsys.readouterr().out
    with serve(out) as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "README.md").read_text() == "# Foo\n"


def test_build_reports_failures_with_exit_code(mono, tmp_path):
    mono.write("partlet.toml", """
[site]
source = "s"
base_url = "https://x"

[projects.foo]
path = "missing"
approved = "0000000000000000000000000000000000000000"
""")
    mono.commit("c1")
    assert main(["build", "--repo", str(mono.path), "--out", str(tmp_path / "out")]) == 1


def test_bad_manifest_exit_code(mono, tmp_path, capsys):
    mono.write("partlet.toml", "[site\n")
    mono.commit("c1")
    assert main(["build", "--repo", str(mono.path), "--out", str(tmp_path / "out")]) == 2
    assert "invalid TOML" in capsys.readouterr().err
```

- [ ] **Step 6: Run the CLI tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.cli'`.

- [ ] **Step 7: Implement the CLI**

`src/partlet/cli.py`:

```python
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
    build = sub.add_parser("build", help="publish every approved project into a local directory")
    build.add_argument("--repo", type=Path, default=Path.cwd(), help="monorepo checkout (default: current directory)")
    build.add_argument("--manifest", type=Path, help="manifest file (default: <repo>/partlet.toml)")
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
```

- [ ] **Step 8: Run the whole suite**

Run: `.venv/bin/pytest -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add src/partlet/publish.py src/partlet/cli.py tests/test_publish.py tests/test_cli.py
git commit -m "Add publish pipeline and partlet build command"
```
