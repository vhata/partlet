# Publishing to R2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `partlet publish`, run from a composite GitHub Action in the monorepo's workflow, publishes every approved project to Cloudflare R2. Before anything is uploaded, gitleaks scans each export's full history. A store lock makes sure only one run touches a source at a time. `partlet review` reports on a project's export and writes its approval pin, and `partlet unpublish` removes a project. An end-to-end test clones and pulls through the Worker under `wrangler dev`.

**Architecture:** The publish pipeline from plan 1 stays as it is and writes through the `Store` interface. This plan adds an `R2Store` (boto3 against R2's S3-compatible API) beside `LocalStore`, a conditional create on both (`put_if_absent`), and a lock object built on it. It also adds a gitleaks wrapper that `publish_project` calls before its first upload, tool-version checks, a step summary, and the `publish`, `unpublish`, `unlock` and `review` commands. The composite action installs every Python dependency from a hash-locked requirements file and gitleaks from a checksum-pinned release, then runs Partlet from the action's own checkout.

**Tech Stack:** Python 3.12, boto3 (S3 API), tomlkit, gitleaks 8.30.1, git-filter-repo 2.47.0, moto (local S3 server for tests), PyYAML (tests), GitHub composite actions, wrangler 4 (`wrangler dev --local`, `getPlatformProxy`), Node 22 or newer.

**Spec:** `docs/specs/2026-10-15-partlet-design.md`

### Scope within the spec

This is plan 3 of 3.

1. **Publisher core.** Done (`plans/2026-10-15-publisher-core.md`).
2. **Worker.** Plan 2, being written in parallel.
3. **Publishing to R2 (this plan).** R2 store, gitleaks scanning, `partlet review`, `partlet publish` and `unpublish` (plus `unlock`), GitHub step summary, composite `action.yml`, the end-to-end test through `wrangler dev` and its CI job.

### Dependencies

- **`publish-orphan-sweep` must have landed first.** This plan builds on that branch's design. `cleanup.json` is gone. Every publish, including one that takes the `unchanged` shortcut, ends with `_sweep`, which deletes every key under a project's `git/objects/pack/`, `site/` and `archive/` that neither the live pointers nor `current["previous"]` name. `PackPlan.superseded` is removed and `gitstatic.PACK_EXTS` is added. The sweep uses the existing `Store.list(prefix)`, so `R2Store.list` must page past R2's 1000-key limit (Task 6 tests this with a page size of 2). If the sweep lands with a different shape, adjust the snippets in Tasks 4, 8 and 9 that touch `publish.py`; the rest of this plan does not depend on the sweep's internals. All code below was run on top of that branch's working tree as of 2026-10-17.
- **Task 13 (end-to-end test) depends on plan 2's Worker.** It assumes this interface, matching plan 1's store layout:
  - `worker/package.json` lists `wrangler` as a dev dependency with a lockfile, so `npm ci` in `worker/` provides `worker/node_modules/.bin/wrangler`;
  - `worker/wrangler.toml` declares an R2 binding named `BUCKET` and a `SOURCE` variable;
  - URLs map to keys as in the spec ("Worker" and "R2 layout"), with the store keys listed under Global Constraints below;
  - the Worker works out response content types from the URL and key, not from R2 object metadata (objects seeded from a `LocalStore` carry none);
  - the Worker serves only `<source>/index.html`, `index.json`, `static/` and `p/<name>/...`, so it never serves `<source>/lock`.

  If plan 2 settles on different names (`wrangler.jsonc`, another binding name), change the two constants at the top of the end-to-end files.
- Tasks 1 to 12 do not depend on plan 2.

### Versions checked on 2026-10-17

| Component | Version | Source |
| --- | --- | --- |
| gitleaks | 8.30.1 (released 2026-03-21) | GitHub releases API; SHA-256 values from `gitleaks_8.30.1_checksums.txt`, matching GitHub's asset digests |
| git-filter-repo | 2.47.0 (latest on PyPI) | PyPI |
| boto3 / botocore | 1.43.114 | PyPI |
| moto | 5.2.4 | PyPI |
| tomlkit | 0.15.2 | PyPI |
| wrangler | 4.151.1 (needs Node 22 or newer) | npm registry |
| astral-sh/setup-uv | v10.3.0 = `1c37ad07a6a961277cf70c0d37d6f313000f5884` | GitHub API |
| actions/checkout | v7.0.1 = `3d3c42e5aac5ba805825da76410c181273ba90b1` | GitHub API |

Behaviour this plan relies on, and where it was checked:

- R2 is strongly consistent for reads, lists and deletes once a write returns, and the S3 API and Worker bindings bypass any custom-domain cache (Cloudflare R2 docs, "Consistency model").
- R2's PutObject supports `If-None-Match: *`; with concurrent writers "at most one write succeeds and the others fail with `412 PreconditionFailed`" (R2 docs, "S3 API compatibility"). moto 5.2.4 behaves the same (checked locally).
- R2's boto3 example uses `endpoint_url="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"` and `region_name="auto"`. Jurisdiction buckets use `<ACCOUNT_ID>.eu.` or `.fedramp.` endpoints (R2 docs, boto3 example and API tokens). The checksum settings in Task 6 are a defensive choice; the current R2 boto3 page does not ask for them.
- gitleaks: `gitleaks git` scans a bare repository; `--log-opts`, `--redact`, `--report-format json`, `--report-path`, `--gitleaks-ignore-path` and `--config` behave as Task 3 uses them. Exit code 1 means both "leaks found" and "error", so Task 3 passes `--exit-code 0` and reads findings from the report. Checked with 8.30.1 on a scratch repository.
- Composite actions: every `run` step needs `shell`; inputs are not exported as `INPUT_*` variables; `github.action_path` locates the action's files (GitHub Docs, "Metadata syntax").
- `getPlatformProxy({ persist: { path: "<dir>/v3" } })` shares local storage with `wrangler dev --persist-to <dir>` (wrangler API docs), and `wrangler dev --local` disables remote bindings (wrangler commands docs). Both were checked together with wrangler 4.151.1.

## Global Constraints

- Everything in plan 1's Global Constraints still holds, except as listed here.
- Store keys, all under `<source>/`:
  - `index.html`, `index.json`, `static/style.css`, `lock` (only while a run holds it)
  - `p/<name>/current` (JSON, including `previous`)
  - `p/<name>/git/HEAD`, `p/<name>/git/info/refs`, `p/<name>/git/objects/info/packs`, `p/<name>/git/objects/pack/pack-*.{pack,idx}`
  - `p/<name>/site/<build>/...`
  - `p/<name>/archive/<sha>.{tar.gz,zip}`
  - There is no `cleanup.json`. Nothing else may be stored under `git/objects/pack/`, `site/` or `archive/`, because the sweep deletes every key there that no pointer names.
- Order within one run: take `<source>/lock`. Then, per project: export, history check, the secret scan of the full export history (only if anything will be uploaded), pack files, site build, archives, `objects/info/packs`, `info/refs`, `HEAD`, `current`, then the sweep. After all projects, the site index. The lock is released last.
- Only one run may touch a source at a time. The monorepo workflow declares a `concurrency` group with `cancel-in-progress: false`, and every `build`, `publish` and `unpublish` run holds the store lock. A held lock fails the run; it never waits and never breaks a lock on its own.
- R2 settings come from `PARTLET_R2_ACCOUNT_ID`, `PARTLET_R2_ACCESS_KEY_ID`, `PARTLET_R2_SECRET_ACCESS_KEY`, `PARTLET_R2_BUCKET` and optionally `PARTLET_R2_ENDPOINT`. The two key variables are removed from the process environment as soon as they are read, before any child process starts.
- Pinned tools: gitleaks exactly `8.30.1`, installed only by `scripts/install-gitleaks.sh` with a per-platform SHA-256; git-filter-repo exactly `2.47.0` in `pyproject.toml` and `action/requirements.txt`. `partlet publish`, `partlet review` and `partlet build --scan` refuse any other version. Bumping either pin is its own PR (docs/QUALITY.md).
- Tests never reach the network beyond loopback and never see real credentials (Task 1). The R2 store is tested only against a moto server on `127.0.0.1`.
- The fake secret used in tests is assembled at run time (`"ghp_" + ...`), so no tracked file contains a string shaped like a GitHub token.
- Agents never create or change billable or shared resources: R2 buckets, API tokens, Worker deployments, GitHub secrets, repository settings, release tags. Steps that do are marked **USER STEP** and collected under "User-run steps" at the end; agents write the instructions and stop.
- Changes to `.github/workflows/ci.yml` (Tasks 12 and 13) need the user's word in the turn they are made (`docket/CONTRACT.md`). Ask before committing them.
- Commit messages: imperative subject, no attribution trailers. Before every commit, `bash scripts/check.sh` passes.
- The repository follows `docket/CONTRACT.md` and the Docket section of `AGENTS.md`. Stacked PRs are in force; the suggested split is in "Pull requests" below.

## Review Focus

1. **Credentials never reach logs, child processes or the public Worker.** `R2Config.from_env` removes the key variables from `os.environ` before git, filter-repo or gitleaks start. The config's `repr` and every `StoreError` leave the secret out. The step summary and stdout never contain it. The action passes the secret inputs to the publish step only, through `env:`, never interpolated into a script. The monorepo workflow checks out with `persist-credentials: false`. The Worker gets an R2 binding and nothing else, and the lock object holds no secrets. Tests: Task 6 (`test_from_env_reads_settings_and_removes_the_keys`, `test_errors_and_repr_never_contain_the_secret`), Task 8 (`test_secret_never_reaches_output`, `test_publish_removes_the_keys_from_the_environment`), Task 12 (`test_credentials_reach_only_the_publish_step`, `test_inputs_never_expand_inside_scripts`).
2. **The secret scan covers the full exported history and runs before any upload; a finding blocks the project.** The spec scans only `published..new` in CI. This plan scans everything reachable from the export tip on every run that uploads anything, because CI cannot otherwise prove the local review scan ever happened. A secret in a commit whose file was later deleted still blocks. A blocked first publish leaves no keys at all, and a blocked later publish leaves the published state byte for byte unchanged. Tests: Task 3 (`test_secret_in_a_deleted_file_is_found`, `test_report_is_redacted`), Task 4 (`test_secret_in_history_blocks_first_publish_before_any_upload`, `test_secret_in_new_commit_leaves_published_state_alone`).
3. **CI enforces the approval pin and the fast-forward check.** `check_history` (plan 1) still decides. `partlet publish` adds `check_checkout`: HEAD must be the tip of the local publishing branch and `partlet.toml` must match the committed version, so pins that were never committed cannot be published, and a run from a pull request or another branch cannot publish. The action creates `refs/heads/<branch>` from `origin/<branch>` when the checkout lacks it; the export fails with "branch ... not found" without it. Tests: Task 8 (`test_ci_enforces_the_approval_pin_and_fast_forward`, `test_refuses_a_checkout_of_another_branch`, `test_refuses_without_a_local_publishing_branch`, `test_refuses_an_uncommitted_manifest_edit`), Task 12 smoke job.
4. **Publishes to one source are serialised.** The sweep deletes every unreferenced key under a project's pack, site and archive prefixes, including on the `unchanged` shortcut. A second run could therefore delete packs or a site build that the first has uploaded but not yet pointed at. The first run then writes pointers to missing objects, and later publishes do not repair them: incremental packs exclude everything reachable from the published tip, and an unchanged build is not re-rendered. The workflow's `concurrency` group serialises the runs GitHub knows about. The store lock covers the rest: a local `partlet publish` or `unpublish`, a second workflow or repository using the same source (GitHub concurrency groups are per repository), or a workflow edited without the group. Check that every command that writes holds the lock for its whole run, that the lock is released on failure and on SIGTERM, and that a run never removes a lock it does not hold. Tests: Task 5 (`test_lock_is_exclusive_and_released`, `test_someone_elses_lock_is_left_alone`), Task 6 (`test_put_if_absent_creates_once` against both stores), Task 8 (`test_a_held_lock_stops_the_publish`).
5. **`unpublish` removes everything under `<source>/p/<name>/`, nothing under `p/<name>x/`, and the project's site index entry.** `current` is deleted first and the index rebuilt before the remaining keys, so an interrupted run has already taken the project off the site, and running again finishes the job. It refuses a project that is still approved in the manifest (the next publish would restore it) and rejects names that could widen the prefix. Tests: Task 9.
6. **Upload order and atomicity on R2.** R2 has no multi-object transaction. Each PutObject replaces one object whole, and reads, lists and deletes see completed writes immediately, so the order alone guarantees that no pointer names a missing object: new objects first, then `objects/info/packs`, `info/refs`, `HEAD`, then `current`, then the sweep. The Worker reads through its binding, which the R2 cache never touches. Clients and Cloudflare's edge may still cache `info/refs` and `objects/info/packs` for the 60 seconds the spec allows, while the sweep keeps superseded objects for one publish only. Two publishes less than a minute apart can therefore delete a pack that a cached `objects/info/packs` still lists; the client's fetch fails, and a retry once the cached copy expires succeeds. This plan does not change that; see open question 3.
7. **Retries and idempotency on partial failure.** botocore retries transient errors (standard mode, 5 attempts). Every put and delete is idempotent. Task 7 fails a publish at every single put or delete in turn. After each failure every key the live pointers name must exist and a clone must work; a plain re-run must recover, publish the new tip, and let the earlier clone `git pull`. `NoSuchBucket` is an error, never "nothing published" (Task 6).

Also guarded, with tests in the owning tasks: no test can open a non-loopback connection or inherit cloud credentials (Task 1); a gitleaks or filter-repo build other than the pinned one is refused (Tasks 3 and 4); the action's third-party actions are pinned to commit SHAs and its Python never imports from the monorepo checkout (Task 12).

## Pull requests

Stacked, each on the one before:

1. Tasks 1 to 4: test sandbox, tool pins, secret scanning in the pipeline.
2. Tasks 5 to 9: store lock, R2 store, interruption test, `publish`, `unpublish` and `unlock`.
3. Tasks 10 and 11: manifest editing and `partlet review`.
4. Task 12: the composite action and its smoke job (CI change: needs the user's word).
5. Task 13: the end-to-end test and its CI job, once plan 2's Worker has landed (CI change: needs the user's word).

Task 14 lists the documentation each PR updates; make those changes in the PR whose code makes the old text inaccurate.

---

## File structure

```
pyproject.toml           + boto3, tomlkit; git-filter-repo pinned ==2.47.0; dev: moto[server], pyyaml; e2e marker
action.yml               composite action: install pinned tools, prepare branch, publish
action/requirements.txt  hash-locked runtime dependencies for the action (uv pip compile)
scripts/
  install-gitleaks.sh    pinned, checksum-verified gitleaks download
  setup.sh               + installs gitleaks into .venv/bin
  e2e.sh                 runs the end-to-end test
src/partlet/
  gitutil.py             + clean_env()
  scan.py                GITLEAKS_VERSION, Finding, ScanError, Scanner, check_gitleaks(), scan_history()
  tools.py               FILTER_REPO_VERSION, Tools, ToolError, check_tools()
  store.py               + Store.put_if_absent, StoreError, R2Config, R2Store, R2ClientError
  lock.py                LockError, lock_key(), describe_holder(), read_lock(), store_lock()
  publish.py             + scanner argument, CheckoutError, check_checkout(), unpublish_project()
  summary.py             summary_markdown(), write_summary()
  manifest.py            + set_project_fields()
  review.py              Report, ReviewError, build_report(), fetch_published_tip(), run_review()
  cli.py                 build [--scan] | publish | unpublish | unlock | review
tests/
  conftest.py            + credential stripping, loopback-only sockets, moto fixtures
  helpers.py             + CLOUD_PREFIXES, fake R2 keys, export_tip(), mirror_store()
  test_sandbox.py        + credential and network tests
  test_scan.py, test_tools.py, test_publish_scan.py
  test_lock.py, test_r2_store.py, test_publish_interrupted.py
  test_cli_publish.py, test_summary.py, test_unpublish.py
  test_manifest_edit.py, test_review.py, test_action.py
  e2e/
    seed_local_r2.mjs    mirrors a LocalStore directory into wrangler's local R2
    test_wrangler.py     publish, serve with wrangler dev, clone, publish, pull
.github/workflows/ci.yml + action smoke job, e2e job
```

---

### Task 1: Test sandbox without cloud credentials or outside network

Queue area `[TOOLING]`. Required by the TODO entry: no test may reach a real bucket.

**Files:**
- Modify: `tests/conftest.py`, `tests/helpers.py`, `tests/test_sandbox.py`

**Interfaces:**
- Consumes: the existing sandbox (`_git_sandbox`, `SANDBOX_TESTS`).
- Produces:
  - `helpers.CLOUD_PREFIXES: tuple[str, ...]`, `helpers.SANDBOX_AWS_VARS: tuple[str, ...]`
  - every test runs without `AWS_*`, `R2_*`, `PARTLET_R2_*`, `CLOUDFLARE_*`, `CF_*`, `WRANGLER_*` or `GITLEAKS_*` variables, except the three AWS variables the sandbox sets itself
  - `socket.socket.connect` and `connect_ex` raise `NetworkBlocked` (an `OSError`) for any non-loopback address

- [ ] **Step 1: Write the failing tests**

In `tests/helpers.py`, after `EPOCH = ...`, add:

```python
# Variables that carry credentials or endpoints for R2, AWS SDKs, Cloudflare
# and wrangler, plus gitleaks configuration, which tests always pass
# explicitly. Tests never inherit any of them.
CLOUD_PREFIXES = (
    "AWS_",
    "R2_",
    "PARTLET_R2_",
    "CLOUDFLARE_",
    "CF_",
    "WRANGLER_",
    "GITLEAKS_",
)
# Set by the sandbox itself, so the AWS SDK finds no shared config and never
# asks an instance metadata service for credentials.
SANDBOX_AWS_VARS = (
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_EC2_METADATA_DISABLED",
)
```

In `tests/test_sandbox.py`: add `import socket` to the imports, add `CLOUD_PREFIXES` and `SANDBOX_AWS_VARS` to the `from helpers import (...)` list, and append `"test_no_cloud_credentials"` and `"test_network_is_loopback_only"` to `SANDBOX_TESTS`. In `test_sandbox_holds_inside_an_enclosing_repository`, after the line that sets `env["GIT_WORK_TREE"]`, add:

```python
    # Credentials the inner run must strip before any test sees them.
    env["AWS_ACCESS_KEY_ID"] = "AKIA-sandbox-test"
    env["PARTLET_R2_SECRET_ACCESS_KEY"] = "sandbox-test-secret"
    env["CLOUDFLARE_API_TOKEN"] = "sandbox-test-token"
```

Append to `tests/test_sandbox.py`:

```python
def test_no_cloud_credentials():
    leaked = [
        k
        for k in os.environ
        if k.startswith(CLOUD_PREFIXES) and k not in SANDBOX_AWS_VARS
    ]
    assert leaked == []
    assert os.environ["AWS_EC2_METADATA_DISABLED"] == "true"
    for name in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        path = Path(os.environ[name])
        assert path.parent.parent == Path(os.environ["HOME"])
        assert not path.exists()


def test_network_is_loopback_only():
    # 192.0.2.0/24 is reserved for documentation; nothing answers there.
    with pytest.raises(OSError, match="test sandbox"):
        socket.create_connection(("192.0.2.1", 443), timeout=1)
    with socket.create_server(("127.0.0.1", 0)) as server:
        socket.create_connection(server.getsockname(), timeout=1).close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sandbox.py -v`
Expected: FAIL. `test_no_cloud_credentials` fails with `KeyError: 'AWS_EC2_METADATA_DISABLED'` (or a non-empty `leaked` list), `test_network_is_loopback_only` fails because the error is a timeout, not "test sandbox", and `test_sandbox_holds_inside_an_enclosing_repository` fails because the inner run fails both.

- [ ] **Step 3: Strip credentials and allow loopback connections only**

In `tests/conftest.py`:

1. Replace items 1 and 3 of the module docstring with:

```
1. At import, inherited `GIT_*` variables and cloud credentials are removed
   from the process, so nothing that happens during collection can act on an
   enclosing repository or reach a real bucket.
```

```
3. The session fixture `_git_sandbox` moves HOME, the global git config and
   the working directory into pytest's temporary area, and sets
   GIT_CEILING_DIRECTORIES so repository discovery cannot leave it. It also
   points the AWS SDK at missing config files and allows sockets to connect
   to loopback addresses only, so the R2 store's tests can reach a local fake
   endpoint and nothing else.
```

2. Add `import ipaddress` and `import socket` to the imports, and `CLOUD_PREFIXES` to the `from helpers import (...)` list.

3. Replace the import-time loop with:

```python
for _name in [k for k in os.environ if k.startswith(("GIT_", *CLOUD_PREFIXES))]:
    del os.environ[_name]
```

4. Above the `_git_sandbox` fixture, add:

```python
class NetworkBlocked(OSError):
    """A test tried to open a connection to a non-loopback address."""


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _guard(real):
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(
            str(address[0])
        ):
            raise NetworkBlocked(f"test sandbox: connection to {address[0]} blocked")
        return real(sock, address)

    return connect
```

5. In `_git_sandbox`, make the `delenv` loop cover the same prefixes:

```python
        for name in [k for k in os.environ if k.startswith(("GIT_", *CLOUD_PREFIXES))]:
            mp.delenv(name)
```

and after the `GIT_CEILING_DIRECTORIES` line add:

```python
        mp.setenv("AWS_CONFIG_FILE", str(home / ".aws" / "config"))
        mp.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws" / "credentials"))
        mp.setenv("AWS_EC2_METADATA_DISABLED", "true")
        mp.setattr(socket.socket, "connect", _guard(socket.socket.connect))
        mp.setattr(socket.socket, "connect_ex", _guard(socket.socket.connect_ex))
```

Subprocesses (git, gitleaks, wrangler) are not covered by the socket guard; they inherit the stripped environment, and the tests only point them at local paths or loopback URLs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sandbox.py -v`
Expected: all PASS, including `test_sandbox_holds_inside_an_enclosing_repository` (its inner run reports `7 passed`).

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`. The existing tests use loopback only (`serve_directory` binds `127.0.0.1`).

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/helpers.py tests/test_sandbox.py
git commit -m "Strip cloud credentials and outside network from the test sandbox"
```

---

### Task 2: Pin git-filter-repo exactly and install a pinned gitleaks

Queue area `[TOOLING]`.

**Files:**
- Create: `scripts/install-gitleaks.sh`
- Modify: `pyproject.toml`, `scripts/setup.sh`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `bash scripts/install-gitleaks.sh [DEST]` installs gitleaks 8.30.1 into `DEST` (default `.venv/bin`) after checking its SHA-256, and does nothing if that version is already there
  - `pyproject.toml` requires `git-filter-repo==2.47.0`

- [ ] **Step 1: Pin git-filter-repo**

In `pyproject.toml`, change `"git-filter-repo>=2.38",` to `"git-filter-repo==2.47.0",`. 2.47.0 is the latest release on PyPI (2024-12-04) and the version the existing export tests ran against. Task 4 adds the test that keeps this pin and `tools.FILTER_REPO_VERSION` in step.

- [ ] **Step 2: Write the installer**

`scripts/install-gitleaks.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# Install the pinned gitleaks release into DEST (default: this worktree's
# .venv/bin) after checking the download against the SHA-256 recorded here.
# scripts/setup.sh and action.yml both call it, so development, CI and the
# action run the same build. Partlet's scan.py refuses any other version.
# To bump: change VERSION and the four hashes, taken from the release's
# gitleaks_<VERSION>_checksums.txt, together with GITLEAKS_VERSION in
# src/partlet/scan.py, in a PR of its own.
set -euo pipefail

VERSION=8.30.1
dest=${1:-"$(cd "$(dirname "$0")/.." && pwd)/.venv/bin"}

case "$(uname -s)-$(uname -m)" in
  Linux-x86_64) platform=linux_x64 sha256=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb ;;
  Linux-aarch64 | Linux-arm64) platform=linux_arm64 sha256=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080 ;;
  Darwin-x86_64) platform=darwin_x64 sha256=dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709 ;;
  Darwin-arm64) platform=darwin_arm64 sha256=b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5 ;;
  *) echo "install-gitleaks: no pinned build for $(uname -s) $(uname -m)" >&2; exit 1 ;;
esac

if [ -x "$dest/gitleaks" ] && [ "$("$dest/gitleaks" version 2>/dev/null)" = "$VERSION" ]; then
  echo "install-gitleaks: gitleaks $VERSION already in $dest"
  exit 0
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
archive="gitleaks_${VERSION}_${platform}.tar.gz"
curl -fsSL --retry 3 -o "$tmp/$archive" \
  "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/${archive}"
if command -v sha256sum >/dev/null; then
  actual=$(sha256sum "$tmp/$archive" | cut -d' ' -f1)
else
  actual=$(shasum -a 256 "$tmp/$archive" | cut -d' ' -f1)
fi
if [ "$actual" != "$sha256" ]; then
  echo "install-gitleaks: checksum mismatch for $archive: expected $sha256, got $actual" >&2
  exit 1
fi
mkdir "$tmp/unpacked"
tar -xzf "$tmp/$archive" -C "$tmp/unpacked" gitleaks
mkdir -p "$dest"
install -m 0755 "$tmp/unpacked/gitleaks" "$dest/gitleaks"
echo "install-gitleaks: installed gitleaks $VERSION in $dest"
```

The four hashes are the `linux_x64`, `linux_arm64`, `darwin_x64` and `darwin_arm64` lines of `gitleaks_8.30.1_checksums.txt`, and they match the SHA-256 digests GitHub lists for those assets.

- [ ] **Step 3: Install gitleaks from setup.sh**

In `scripts/setup.sh`, after the `uv pip install ...` line, add:

```bash
# gitleaks, at the version and checksum pinned in the script.
bash scripts/install-gitleaks.sh .venv/bin
```

- [ ] **Step 4: Verify**

Run: `chmod +x scripts/install-gitleaks.sh && bash scripts/setup.sh`
Expected: `install-gitleaks: installed gitleaks 8.30.1 in .../.venv/bin`, then `setup: done.`

Run: `.venv/bin/gitleaks version && bash scripts/install-gitleaks.sh`
Expected: `8.30.1`, then `install-gitleaks: gitleaks 8.30.1 already in .../.venv/bin`.

Run (checks the checksum guard; restores the file afterwards): `sed -i.bak 's/=b40ab0ae/=000ab0ae/; s/=551f6fc8/=000f6fc8/' scripts/install-gitleaks.sh && bash scripts/install-gitleaks.sh "$(mktemp -d)"; mv scripts/install-gitleaks.sh.bak scripts/install-gitleaks.sh`
Expected: on macOS arm64 or Linux x86_64, `install-gitleaks: checksum mismatch for gitleaks_8.30.1_<platform>.tar.gz: expected 000..., got ...` and exit status 1. On other platforms, change that platform's hash instead.

Run: `.venv/bin/python -c "import importlib.metadata as m; print(m.version('git-filter-repo'))" && bash scripts/check.sh`
Expected: `2.47.0`, then `check: all gates passed` (shellcheck now also covers the installer).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml scripts/install-gitleaks.sh scripts/setup.sh
git commit -m "Pin git-filter-repo exactly and install a checksum-pinned gitleaks"
```

---

### Task 3: Secret scanning with gitleaks

Queue area `[PUBLISHER]`.

**Files:**
- Create: `src/partlet/scan.py`
- Modify: `src/partlet/gitutil.py`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `gitutil` (Task 2 of plan 1), the gitleaks from Task 2.
- Produces:
  - `gitutil.clean_env() -> dict[str, str]` (the environment without the variables that redirect git; `_run` uses it)
  - `scan.GITLEAKS_VERSION = "8.30.1"`
  - `class ScanError(Exception)`
  - `@dataclass(frozen=True) class Finding(rule: str, commit: str, file: str, line: int, fingerprint: str)` with `describe() -> str`
  - `find_gitleaks() -> str`, `check_gitleaks(binary: str | None = None) -> str` (path of a gitleaks that is exactly the pinned version)
  - `scan_history(repo: Path, config_dir: Path, workdir: Path, binary: str) -> list[Finding]` (everything reachable from `refs/heads/main`; `config_dir` is the monorepo root, whose `.gitleaks.toml` and `.gitleaksignore` apply)
  - `@dataclass(frozen=True) class Scanner(binary: str, config_dir: Path)` with `scan(repo: Path, workdir: Path) -> list[Finding]`

- [ ] **Step 1: Write the failing tests**

`tests/test_scan.py`:

```python
import json
import re
from pathlib import Path

import pytest

from partlet.scan import (
    GITLEAKS_VERSION,
    ScanError,
    Scanner,
    check_gitleaks,
    scan_history,
)

ROOT = Path(__file__).resolve().parent.parent

# Built at run time so this file holds no string that looks like a token.
FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


def scan(mono, tmp_path, gitleaks):
    return Scanner(gitleaks, mono.path).scan(mono.path, tmp_path / "scan")


def test_pinned_version_matches_installer():
    script = (ROOT / "scripts" / "install-gitleaks.sh").read_text()
    assert (
        re.search(r"^VERSION=(\S+)$", script, re.MULTILINE).group(1) == GITLEAKS_VERSION
    )


def test_clean_history_has_no_findings(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "nothing to see\n")
    mono.commit("c1")
    assert scan(mono, tmp_path, gitleaks) == []


def test_secret_in_a_deleted_file_is_found(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    leaky = mono.commit("add token")
    mono.rm("foo/config.py")
    mono.commit("remove token")
    findings = scan(mono, tmp_path, gitleaks)
    assert [(f.rule, f.file, f.commit, f.line) for f in findings] == [
        ("github-pat", "foo/config.py", leaky, 1)
    ]
    assert FAKE_TOKEN not in findings[0].describe()


def test_report_is_redacted(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("add token")
    scan(mono, tmp_path, gitleaks)
    report = (tmp_path / "scan" / "gitleaks.json").read_text()
    assert FAKE_TOKEN not in report
    assert json.loads(report)[0]["Secret"] == "REDACTED"


def test_monorepo_config_allowlists_paths(mono, tmp_path, gitleaks):
    mono.write("foo/fixtures/token.txt", FAKE_TOKEN + "\n")
    mono.write(
        ".gitleaks.toml",
        '[extend]\nuseDefault = true\n\n[allowlist]\npaths = ["fixtures/"]\n',
    )
    mono.commit("c1")
    assert scan(mono, tmp_path, gitleaks) == []


def test_gitleaksignore_accepts_a_fingerprint(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    (finding,) = scan(mono, tmp_path, gitleaks)
    (mono.path / ".gitleaksignore").write_text(finding.fingerprint + "\n")
    assert scan(mono, tmp_path / "again", gitleaks) == []


def test_wrong_version_is_refused(tmp_path):
    fake = tmp_path / "gitleaks"
    fake.write_text("#!/bin/sh\necho 8.0.0\n")
    fake.chmod(0o755)
    with pytest.raises(ScanError, match=f"needs gitleaks {GITLEAKS_VERSION}"):
        check_gitleaks(str(fake))


def test_gitleaks_failure_is_an_error(tmp_path, gitleaks):
    with pytest.raises(ScanError, match="gitleaks failed"):
        scan_history(tmp_path / "missing.git", tmp_path, tmp_path / "scan", gitleaks)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.scan'`.

- [ ] **Step 3: Implement**

In `src/partlet/gitutil.py`, add above `_run`:

```python
def clean_env() -> dict[str, str]:
    """The process environment without the variables that redirect git."""
    return {k: v for k, v in os.environ.items() if k not in _LOCAL_ENV_VARS}
```

and in `_run` replace the two lines that build `inherited` and `full_env` with:

```python
    full_env = {**clean_env(), **(env or {})}
```

`src/partlet/scan.py`:

```python
"""Scan an export's full history for secrets with a pinned gitleaks release."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from partlet.gitutil import clean_env

# Must match VERSION in scripts/install-gitleaks.sh (tests/test_scan.py checks).
GITLEAKS_VERSION = "8.30.1"


class ScanError(Exception):
    """gitleaks is missing, is not the pinned version, or failed to run."""


@dataclass(frozen=True)
class Finding:
    rule: str
    commit: str
    file: str
    line: int
    fingerprint: str

    def describe(self) -> str:
        return f"{self.rule} in {self.file}:{self.line} at {self.commit[:12]}"


def find_gitleaks() -> str:
    """The gitleaks beside this Python (a virtualenv's bin), else the one on PATH."""
    beside = Path(sys.executable).parent / "gitleaks"
    if beside.is_file():
        return str(beside)
    found = shutil.which("gitleaks")
    if found is None:
        raise ScanError(
            "gitleaks not found; install it with bash scripts/install-gitleaks.sh"
        )
    return found


def _env() -> dict[str, str]:
    # GITLEAKS_CONFIG and GITLEAKS_CONFIG_TOML would override the monorepo's
    # configuration; partlet always passes it explicitly.
    return {k: v for k, v in clean_env().items() if not k.startswith("GITLEAKS_")}


def check_gitleaks(binary: str | None = None) -> str:
    """Return the path of a gitleaks that is exactly the pinned version."""
    binary = binary or find_gitleaks()
    try:
        proc = subprocess.run(
            [binary, "version"],
            capture_output=True,
            text=True,
            env=_env(),
            check=False,
        )
    except OSError as e:
        raise ScanError(f"cannot run {binary}: {e}") from e
    version = proc.stdout.strip().removeprefix("v")
    if proc.returncode != 0 or version != GITLEAKS_VERSION:
        raise ScanError(
            f"{binary} reports version {version or '(none)'}; partlet needs gitleaks "
            f"{GITLEAKS_VERSION} exactly (bash scripts/install-gitleaks.sh)"
        )
    return binary


def scan_history(
    repo: Path, config_dir: Path, workdir: Path, binary: str
) -> list[Finding]:
    """Scan every commit reachable from refs/heads/main in `repo`.

    `config_dir` is the monorepo root. Its `.gitleaks.toml`, if present, is the
    gitleaks configuration, and its `.gitleaksignore`, if present, lists accepted
    findings by fingerprint. Secrets are redacted in the report, so a Finding
    never carries one.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    report = workdir / "gitleaks.json"
    cmd = [
        binary,
        "git",
        "--no-banner",
        "--no-color",
        "--redact",
        "--exit-code",
        "0",  # findings come from the report; a non-zero exit is an error
        "--log-level",
        "error",
        "--report-format",
        "json",
        "--report-path",
        str(report),
        "--gitleaks-ignore-path",
        str(config_dir),
        "--log-opts",
        "refs/heads/main",
    ]
    config = config_dir / ".gitleaks.toml"
    if config.is_file():
        cmd += ["--config", str(config)]
    cmd.append(str(repo))
    proc = subprocess.run(
        cmd, cwd=workdir, capture_output=True, text=True, env=_env(), check=False
    )
    if proc.returncode != 0:
        raise ScanError(f"gitleaks failed ({proc.returncode}): {proc.stderr.strip()}")
    try:
        items = json.loads(report.read_text(encoding="utf-8"))
        return [
            Finding(
                rule=item["RuleID"],
                commit=item["Commit"],
                file=item["File"],
                line=int(item["StartLine"]),
                fingerprint=item["Fingerprint"],
            )
            for item in items
        ]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ScanError(f"cannot read the gitleaks report: {e}") from e


@dataclass(frozen=True)
class Scanner:
    """A checked gitleaks binary and the monorepo whose configuration it uses."""

    binary: str
    config_dir: Path

    def scan(self, repo: Path, workdir: Path) -> list[Finding]:
        return scan_history(repo, self.config_dir, workdir, self.binary)
```

Why `--exit-code 0`: gitleaks exits 1 both when it finds leaks and when it fails, so the exit status alone cannot tell a finding from a broken scan. With `--exit-code 0` any non-zero exit is an error, and findings come from the JSON report. `--redact` replaces `Secret` and `Match` with `REDACTED` in the report, so no `Finding` holds a secret. `--gitleaks-ignore-path` must always be given: its default is the current directory.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_scan.py tests/test_gitutil.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/scan.py src/partlet/gitutil.py tests/test_scan.py
git commit -m "Add secret scanning of an export's full history with gitleaks"
```

---

### Task 4: Tool checks, and the scan before any upload

Queue area `[PUBLISHER]`.

**Files:**
- Create: `src/partlet/tools.py`
- Modify: `src/partlet/publish.py`, `tests/helpers.py`
- Test: `tests/test_tools.py`, `tests/test_publish_scan.py`

**Interfaces:**
- Consumes: `scan` (Task 3), `publish_project` and `publish_all` as left by `publish-orphan-sweep`.
- Produces:
  - `tools.FILTER_REPO_VERSION = "2.47.0"`, `class ToolError(Exception)`, `@dataclass(frozen=True) class Tools(versions: dict[str, str], gitleaks: str | None)`, `check_tools(*, gitleaks: bool) -> Tools`
  - `publish_project(..., workdir, scanner: Scanner | None = None)` and `publish_all(..., workdir, scanner: Scanner | None = None)`: with a scanner, a project whose export history has any finding fails before its first store write
  - `helpers.export_tip(mono, tmp_path, name="foo", path=None) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/helpers.py`:

```python
def export_tip(
    mono: Repo, tmp_path: Path, name: str = "foo", path: str | None = None
) -> str:
    """The tip `partlet review` would show for a project: export once and read it."""
    from partlet.export import export_project
    from partlet.manifest import Project

    dest = tmp_path / f"probe-{name}-{len(list(tmp_path.glob(f'probe-{name}-*')))}.git"
    return export_project(mono.path, "main", Project(name, path or name), dest)
```

`tests/test_tools.py`:

```python
import importlib.metadata
import tomllib
from pathlib import Path

import pytest

from partlet import tools
from partlet.scan import GITLEAKS_VERSION
from partlet.tools import FILTER_REPO_VERSION, ToolError, check_tools

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_pins_filter_repo_exactly():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    assert f"git-filter-repo=={FILTER_REPO_VERSION}" in deps


def test_check_tools_reports_pinned_versions():
    found = check_tools(gitleaks=True)
    assert found.versions["git-filter-repo"] == FILTER_REPO_VERSION
    assert found.versions["gitleaks"] == GITLEAKS_VERSION
    assert found.versions["git"][0].isdigit()
    assert found.gitleaks is not None


def test_other_filter_repo_release_is_refused(monkeypatch):
    real = importlib.metadata.version
    monkeypatch.setattr(
        tools.importlib.metadata,
        "version",
        lambda name: "2.38.0" if name == "git-filter-repo" else real(name),
    )
    with pytest.raises(ToolError, match=f"exactly {FILTER_REPO_VERSION}"):
        check_tools(gitleaks=False)
```

`tests/test_publish_scan.py`:

```python
import json

import pytest
from helpers import export_tip

from partlet.manifest import parse_manifest
from partlet.publish import publish_all
from partlet.scan import Scanner, check_gitleaks
from partlet.store import LocalStore

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


def publish(mono, tmp_path, store, approved, gitleaks):
    m = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""")
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    (result,) = publish_all(mono.path, m, store, work, Scanner(gitleaks, mono.path))
    return result


def test_secret_in_history_blocks_first_publish_before_any_upload(
    mono, tmp_path, gitleaks
):
    mono.write("foo/a.txt", "one\n")
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    mono.rm("foo/config.py")
    mono.commit("remove the token again")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")

    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert "secret scan: 1 finding(s): github-pat in config.py:1" in result.reason
    assert FAKE_TOKEN not in result.reason
    assert store.list("s/p/foo/") == []
    assert json.loads(store.get("s/index.json")) == []


def test_secret_in_new_commit_leaves_published_state_alone(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    assert publish(mono, tmp_path, store, approved, gitleaks).status == "published"
    before = {key: store.get(key) for key in store.list("s/p/foo/")}

    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c2")
    result = publish(mono, tmp_path, store, approved, gitleaks)
    assert result.status == "failed"
    assert {key: store.get(key) for key in store.list("s/p/foo/")} == before


def test_monorepo_gitleaks_config_is_used(mono, tmp_path, gitleaks):
    mono.write("foo/fixtures/token.txt", FAKE_TOKEN + "\n")
    mono.write(
        ".gitleaks.toml",
        '[extend]\nuseDefault = true\n\n[allowlist]\npaths = ["fixtures/"]\n',
    )
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    assert publish(mono, tmp_path, store, approved, gitleaks).status == "published"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_tools.py tests/test_publish_scan.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.tools'` and `TypeError: publish_all() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3: Implement**

`src/partlet/tools.py`:

```python
"""Check the external tools whose versions published output depends on."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path

from partlet import __version__
from partlet.gitutil import GitError, git_out
from partlet.scan import GITLEAKS_VERSION, ScanError, check_gitleaks

# Export commit hashes depend on filter-repo's behaviour (docs/DECISIONS.md),
# so publishing refuses any other release. Must match pyproject.toml.
FILTER_REPO_VERSION = "2.47.0"


class ToolError(Exception):
    """A required tool is missing or is not the pinned version."""


@dataclass(frozen=True)
class Tools:
    versions: dict[str, str]
    gitleaks: str | None  # path of the checked gitleaks binary


def check_tools(*, gitleaks: bool) -> Tools:
    try:
        filter_repo = importlib.metadata.version("git-filter-repo")
    except importlib.metadata.PackageNotFoundError as e:
        raise ToolError("git-filter-repo is not installed") from e
    if filter_repo != FILTER_REPO_VERSION:
        raise ToolError(
            f"git-filter-repo {filter_repo} is installed; publishing needs exactly "
            f"{FILTER_REPO_VERSION}, because export commit hashes depend on it"
        )
    try:
        git_version = git_out("--version", cwd=Path.cwd()).removeprefix("git version ")
    except GitError as e:
        raise ToolError(f"cannot run git: {e}") from e
    versions = {
        "partlet": __version__,
        "git": git_version,
        "git-filter-repo": filter_repo,
    }
    binary = None
    if gitleaks:
        try:
            binary = check_gitleaks()
        except ScanError as e:
            raise ToolError(str(e)) from e
        versions["gitleaks"] = GITLEAKS_VERSION
    return Tools(versions, binary)
```

In `src/partlet/publish.py`:

1. Add `from partlet.scan import ScanError, Scanner` to the imports.
2. Give `publish_project` a last parameter `scanner: Scanner | None = None`.
3. Directly after the `unchanged` shortcut's `return`, before the `# 1. New objects first` comment, insert:

```python
        # 0. Nothing is uploaded until the whole export history scans clean.
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
```

4. Change `except (ExportError, HistoryError, GitError) as e:` to `except (ExportError, HistoryError, GitError, ScanError) as e:`.
5. Give `publish_all` the same last parameter, and pass it on:

```python
def publish_all(
    monorepo: Path,
    manifest: Manifest,
    store: Store,
    workdir: Path,
    scanner: Scanner | None = None,
) -> list[ProjectResult]:
```

```python
            result = publish_project(
                monorepo, manifest, project, store, workdir, scanner
            )
```

The scan sits after the `unchanged` shortcut, which uploads nothing, and before the pack upload, which is the first write. It runs on every other path, including a re-render of an already-published tip: one rule ("scan before any upload") is easier to check than a list of exceptions.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_tools.py tests/test_publish_scan.py tests/test_publish.py -v`
Expected: all PASS.

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/tools.py src/partlet/publish.py tests/helpers.py tests/test_tools.py tests/test_publish_scan.py
git commit -m "Scan each export's full history before any upload"
```

---

### Task 5: Conditional create and the publish lock

Queue area `[PUBLISHER]`.

**Files:**
- Create: `src/partlet/lock.py`
- Modify: `src/partlet/store.py`, `tests/test_store.py`
- Test: `tests/test_lock.py`

**Interfaces:**
- Consumes: `Store`, `LocalStore` (plan 1).
- Produces:
  - `Store.put_if_absent(key: str, data: bytes, content_type: str | None = None) -> bool`: creates the key only if it does not exist, atomically; returns whether it did
  - `LocalStore.put_if_absent` (via `os.link`, which fails if the target exists), `LocalStore.__repr__`
  - `class LockError(Exception)`, `lock_key(source: str) -> str` (`"<source>/lock"`), `describe_holder(environ=os.environ) -> str`, `read_lock(store, source) -> dict | None`, `store_lock(store: Store, source: str, holder: str)` (context manager)

**Why a lock as well as the workflow's concurrency group:** the group is the primary control and the action's documentation requires it (Task 14). It cannot see runs outside that one workflow: a local `partlet publish` or `unpublish`, a second workflow or repository that publishes the same source (groups are per repository), or a workflow edited without the group. With the sweep, any overlap can leave pointers naming deleted objects, which later publishes do not repair (Review Focus 4). R2 documents at-most-one-success for a PutObject with `If-None-Match: *`, so the lock costs one conditional put and one delete per run.

It fails closed. A run that finds the lock exits non-zero, naming the holder and when it took the lock. Nothing expires or breaks a lock automatically, because expiring the lock of a slow but live publish would reopen the race this lock exists to close. A run killed without warning (SIGKILL, a lost runner) leaves its lock behind, and the user clears it with `partlet unlock` (Task 9) after checking that the run is gone. Python's `finally` releases the lock on errors, Ctrl-C (`KeyboardInterrupt`) and, through the handler Task 8 installs, SIGTERM.

- [ ] **Step 1: Write the failing tests**

`tests/test_lock.py`:

```python
import json

import pytest

from partlet.lock import LockError, describe_holder, read_lock, store_lock
from partlet.store import LocalStore


def test_lock_is_exclusive_and_released(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "s", "first run"):
        held = json.loads(store.get("s/lock"))
        assert held["holder"] == "first run"
        with pytest.raises(LockError, match="locked by first run"):
            store_lock(store, "s", "second run").__enter__()
        assert read_lock(store, "s")["holder"] == "first run"
    assert store.get("s/lock") is None


def test_lock_is_released_when_the_body_fails(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(RuntimeError), store_lock(store, "s", "run"):
        raise RuntimeError("publish failed")
    assert store.get("s/lock") is None


def test_someone_elses_lock_is_left_alone(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "s", "first run"):
        # `partlet unlock`, then another run takes the lock.
        store.delete("s/lock")
        store.put_if_absent("s/lock", b'{"holder": "other", "token": "x"}')
    assert read_lock(store, "s")["holder"] == "other"


def test_lock_is_per_source(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "a", "run"), store_lock(store, "b", "run"):
        assert store.get("a/lock") and store.get("b/lock")


def test_describe_holder():
    env = {
        "GITHUB_RUN_ID": "42",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "me/mono",
    }
    assert describe_holder(env) == "https://github.com/me/mono/actions/runs/42"
    assert " pid " in describe_holder({})
```

Append to `tests/test_store.py`:

```python
def test_put_if_absent_creates_once(tmp_path):
    s = LocalStore(tmp_path)
    assert s.put_if_absent("s/lock", b"first")
    assert not s.put_if_absent("s/lock", b"second")
    assert s.get("s/lock") == b"first"
    assert [p.name for p in (tmp_path / "s").iterdir()] == ["lock"]  # no temp files
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_lock.py tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.lock'` and `AttributeError: 'LocalStore' object has no attribute 'put_if_absent'`.

- [ ] **Step 3: Implement**

In `src/partlet/store.py`, add to the `Store` protocol, after `put`:

```python
    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool: ...
```

In `LocalStore`, add after `__init__`:

```python
    def __repr__(self) -> str:
        return f"LocalStore({str(self.root)!r})"
```

and replace `put` with these three methods:

```python
    def _write_temp(self, path: Path, data: bytes) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TMP_PREFIX)
        try:
            # mkstemp creates the file 0600; previews must be readable by any
            # static HTTP server, which may run as another user.
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o666 & ~_UMASK)
                f.write(data)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return tmp

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        tmp = self._write_temp(path, data)
        try:
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool:
        path = self._path(key)
        tmp = self._write_temp(path, data)
        try:
            os.link(tmp, path)  # atomic, and fails if `path` exists
        except FileExistsError:
            return False
        finally:
            Path(tmp).unlink(missing_ok=True)
        return True
```

`src/partlet/lock.py`:

```python
"""One run at a time per source: a lock object created with a conditional put.

Every publish ends by sweeping keys that no pointer names, so a second run
against the same source could delete objects the first has uploaded but not
yet pointed at. The workflow's concurrency group serialises CI runs; this lock
also covers runs it cannot see (a local `partlet publish` or `unpublish`, or
another repository or workflow publishing the same source).
"""

from __future__ import annotations

import json
import os
import secrets
import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime

from partlet.store import Store


class LockError(Exception):
    """Another run holds the source's lock."""


def lock_key(source: str) -> str:
    return f"{source}/lock"


def describe_holder(environ: Mapping[str, str] = os.environ) -> str:
    """The GitHub Actions run URL in CI, otherwise host and process ID."""
    if environ.get("GITHUB_RUN_ID"):
        return (
            f"{environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{environ.get('GITHUB_REPOSITORY', '?')}/actions/runs/"
            f"{environ['GITHUB_RUN_ID']}"
        )
    return f"{socket.gethostname()} pid {os.getpid()}"


def read_lock(store: Store, source: str) -> dict | None:
    raw = store.get(lock_key(source))
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return {"holder": "(unreadable lock)", "since": "?"}
    return value if isinstance(value, dict) else {"holder": "?", "since": "?"}


@contextmanager
def store_lock(store: Store, source: str, holder: str) -> Iterator[None]:
    token = secrets.token_hex(16)
    body = {
        "holder": holder,
        "since": datetime.now(UTC).isoformat(timespec="seconds"),
        "token": token,
    }
    data = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    if not store.put_if_absent(lock_key(source), data, "application/json"):
        held = read_lock(store, source) or {}
        raise LockError(
            f"{source} is locked by {held.get('holder', '?')} since "
            f"{held.get('since', '?')}. If no publish is running (a killed job "
            "leaves its lock behind), remove it with: partlet unlock"
        )
    try:
        yield
    finally:
        # Release only our own lock: `partlet unlock` may have removed it and
        # another run taken it since.
        if (read_lock(store, source) or {}).get("token") == token:
            store.delete(lock_key(source))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_lock.py tests/test_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/store.py src/partlet/lock.py tests/test_lock.py tests/test_store.py
git commit -m "Add a conditional create to the store and a per-source publish lock"
```

---

### Task 6: R2 store

Queue area `[PUBLISHER]`. Depends on `publish-orphan-sweep` having landed (its sweep relies on `list` paging).

**Files:**
- Modify: `pyproject.toml`, `src/partlet/store.py`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_lock.py`
- Test: `tests/test_r2_store.py`

**Interfaces:**
- Consumes: `Store` and `check_key` (plan 1, Task 5 of this plan).
- Produces:
  - `class StoreError(Exception)`, `class R2ClientError(StoreError)` with `code: str`, `status: int | None`
  - `@dataclass(frozen=True) class R2Config(bucket: str, endpoint_url: str, access_key_id: str, secret_access_key: str)` (keys excluded from `repr`), `R2Config.from_env(environ: MutableMapping[str, str]) -> R2Config` (removes the two key variables from `environ`)
  - `check_endpoint(url: str) -> str`: `https://<host>`, or plain `http` on loopback only
  - `class R2Store(config: R2Config, *, page_size: int = 1000, max_attempts: int = 5)` implementing every `Store` method; `list` and `list_dirs` follow continuation tokens to the end
  - test fixtures `moto_endpoint` (session), `r2_config` (fresh bucket), `r2_env` (sets `PARTLET_R2_*` for it); `helpers.FAKE_R2_KEY_ID`, `helpers.FAKE_R2_SECRET`, `helpers.mirror_store(store, root)`

- [ ] **Step 1: Add the dependencies**

In `pyproject.toml`, add `"boto3>=1.36",` to `dependencies` (1.36 is the first release with the checksum settings used below) and change the dev extra to:

```toml
dev = ["moto[server]>=5.1", "pytest>=8", "ruff>=0.6"]
```

Run: `bash scripts/setup.sh`
Expected: `setup: done.`

- [ ] **Step 2: Write the fixtures and the failing tests**

In `tests/helpers.py`, after `SANDBOX_AWS_VARS`, add:

```python
# Fake keys for the local moto server that stands in for R2 (conftest.py).
FAKE_R2_KEY_ID = "partlet-test-key-id"
FAKE_R2_SECRET = "partlet-test-secret-do-not-print"
```

and append:

```python
def mirror_store(store, root: Path) -> None:
    """Copy every key of `store` into files under `root`, to serve over HTTP."""
    for key in store.list(""):
        target = root.joinpath(*key.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.get(key))
```

In `tests/conftest.py`, add `import uuid` to the imports and `FAKE_R2_KEY_ID`, `FAKE_R2_SECRET` to the `from helpers import (...)` list, and append:

```python
@pytest.fixture(scope="session")
def moto_endpoint():
    """An S3-compatible server on 127.0.0.1 standing in for R2."""
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


@pytest.fixture
def r2_config(moto_endpoint):
    """An R2Config for a fresh, empty bucket on the moto server."""
    import boto3

    from partlet.store import R2Config

    bucket = f"partlet-test-{uuid.uuid4().hex[:12]}"
    boto3.client(
        "s3",
        endpoint_url=moto_endpoint,
        region_name="us-east-1",  # moto creates buckets only in a real region
        aws_access_key_id=FAKE_R2_KEY_ID,
        aws_secret_access_key=FAKE_R2_SECRET,
    ).create_bucket(Bucket=bucket)
    return R2Config(bucket, moto_endpoint, FAKE_R2_KEY_ID, FAKE_R2_SECRET)


@pytest.fixture
def r2_env(r2_config, monkeypatch):
    """Set the PARTLET_R2_* variables `partlet publish` reads, for the moto bucket."""
    monkeypatch.setenv("PARTLET_R2_ENDPOINT", r2_config.endpoint_url)
    monkeypatch.setenv("PARTLET_R2_BUCKET", r2_config.bucket)
    monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", r2_config.access_key_id)
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", r2_config.secret_access_key)
    return r2_config
```

Append to `tests/test_lock.py`:

```python
def test_lock_on_r2(r2_config):
    from partlet.store import R2Store

    store = R2Store(r2_config)
    with store_lock(store, "s", "ci"), pytest.raises(LockError):
        store_lock(R2Store(r2_config), "s", "laptop").__enter__()
    assert store.get("s/lock") is None
```

`tests/test_r2_store.py`:

```python
import socket

import boto3
import pytest
from helpers import FAKE_R2_SECRET, mirror_store

from partlet.store import LocalStore, R2Config, R2Store, StoreError


@pytest.fixture(params=["local", "r2"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalStore(tmp_path / "out")
    # A page size of 2 makes every listing below span several pages.
    return R2Store(request.getfixturevalue("r2_config"), page_size=2)


def test_put_get_delete(store):
    assert store.get("a/b.txt") is None
    store.put("a/b.txt", b"hello", "text/plain")
    assert store.get("a/b.txt") == b"hello"
    store.put("a/b.txt", b"again")
    assert store.get("a/b.txt") == b"again"
    store.delete("a/b.txt")
    store.delete("a/b.txt")
    assert store.get("a/b.txt") is None


def test_list_and_list_dirs_page_through_everything(store):
    keys = [f"s/p/foo/site/b/raw/f{i:02}.txt" for i in range(7)]
    for key in [*keys, "s/p/foo/current", "s/p/foobar/current", "s/index.html"]:
        store.put(key, b"x")
    assert store.list("s/p/foo/site/") == keys
    assert store.list("s/p/foo/") == ["s/p/foo/current", *keys]
    assert store.list_dirs("s/p/") == ["foo", "foobar"]
    assert store.list_dirs("missing/") == []
    assert len(store.list("")) == 10


def test_names_with_spaces_and_unicode(store):
    store.put("p/site/raw/my file #1 é.txt", b"x")
    assert store.list("p/site/raw/") == ["p/site/raw/my file #1 é.txt"]
    assert store.get("p/site/raw/my file #1 é.txt") == b"x"


def test_put_if_absent_creates_once(store):
    assert store.put_if_absent("s/lock", b"first", "application/json")
    assert not store.put_if_absent("s/lock", b"second")
    assert store.get("s/lock") == b"first"
    store.delete("s/lock")
    assert store.put_if_absent("s/lock", b"third")


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/."])
def test_rejects_bad_keys(store, key):
    with pytest.raises(ValueError):
        store.put(key, b"x")


def test_missing_bucket_is_an_error_not_a_missing_key(r2_config):
    store = R2Store(
        R2Config("partlet-no-such-bucket", r2_config.endpoint_url, "k", "s")
    )
    with pytest.raises(StoreError, match="NoSuchBucket"):
        store.get("s/p/foo/git/info/refs")


def test_content_type_is_stored(r2_config):
    R2Store(r2_config).put("s/index.html", b"<p>", "text/html; charset=utf-8")
    client = boto3.client(
        "s3",
        endpoint_url=r2_config.endpoint_url,
        region_name="us-east-1",
        aws_access_key_id=r2_config.access_key_id,
        aws_secret_access_key=r2_config.secret_access_key,
    )
    head = client.head_object(Bucket=r2_config.bucket, Key="s/index.html")
    assert head["ContentType"] == "text/html; charset=utf-8"


def test_no_ambient_aws_credentials():
    assert boto3.session.Session().get_credentials() is None


def test_from_env_reads_settings_and_removes_the_keys():
    env = {
        "PARTLET_R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
        "PARTLET_R2_ACCESS_KEY_ID": "key-id",
        "PARTLET_R2_SECRET_ACCESS_KEY": "secret-value",
        "PARTLET_R2_BUCKET": "partlet",
        "OTHER": "kept",
    }
    config = R2Config.from_env(env)
    assert config.endpoint_url == (
        "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    )
    assert config.bucket == "partlet"
    assert config.secret_access_key == "secret-value"
    assert env == {
        "PARTLET_R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
        "PARTLET_R2_BUCKET": "partlet",
        "OTHER": "kept",
    }
    assert "secret-value" not in repr(config)
    assert "key-id" not in repr(config)


def test_from_env_endpoint_override():
    env = {
        "PARTLET_R2_ENDPOINT": "https://0123.eu.r2.cloudflarestorage.com",
        "PARTLET_R2_ACCESS_KEY_ID": "k",
        "PARTLET_R2_SECRET_ACCESS_KEY": "s",
        "PARTLET_R2_BUCKET": "b",
    }
    assert R2Config.from_env(env).endpoint_url == env["PARTLET_R2_ENDPOINT"]


def test_from_env_names_missing_settings_without_values():
    env = {"PARTLET_R2_SECRET_ACCESS_KEY": "secret-value"}
    with pytest.raises(StoreError) as e:
        R2Config.from_env(env)
    message = str(e.value)
    assert "PARTLET_R2_ACCESS_KEY_ID" in message
    assert "PARTLET_R2_BUCKET" in message
    assert "PARTLET_R2_ACCOUNT_ID" in message
    assert "secret-value" not in message
    assert env == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://abc.r2.cloudflarestorage.com",
        "https://user:pw@abc.r2.cloudflarestorage.com",
        "https://abc.r2.cloudflarestorage.com/bucket",
        "ftp://127.0.0.1",
    ],
)
def test_unsafe_endpoints_are_refused(url):
    with pytest.raises(StoreError, match="R2 endpoint"):
        R2Store(R2Config("b", url, "k", "s"))


def test_errors_and_repr_never_contain_the_secret(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again: nothing listens there
    store = R2Store(
        R2Config("b", f"http://127.0.0.1:{port}", "k", FAKE_R2_SECRET),
        max_attempts=1,
    )
    assert FAKE_R2_SECRET not in repr(store)
    with pytest.raises(StoreError) as e:
        store.get("s/index.html")
    assert FAKE_R2_SECRET not in str(e.value)
    assert FAKE_R2_SECRET not in repr(e.value)


def test_mirror_of_r2_store_is_cloneable(r2_config, tmp_path, mono, serve):
    from helpers import export_tip

    from partlet.gitutil import git
    from partlet.manifest import parse_manifest
    from partlet.publish import publish_all

    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    m = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""")
    store = R2Store(r2_config, page_size=3)
    (result,) = publish_all(mono.path, m, store, tmp_path / "w1")
    assert result.status == "published"
    mirror_store(store, tmp_path / "site")
    with serve(tmp_path / "site") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "README.md").read_text() == "# Foo\n"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_r2_store.py tests/test_lock.py -v`
Expected: FAIL with `ImportError: cannot import name 'R2Config' from 'partlet.store'`.

- [ ] **Step 4: Implement**

Replace `src/partlet/store.py` with the following. The `Store` protocol and `LocalStore` are as Task 5 left them; what is new is `StoreError`, the imports, and everything from `R2_ENV` down.

```python
"""Where published files go: a key/value interface over R2 or a local directory."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

# Read the umask once without leaving it changed; os.umask can only set it.
_UMASK = os.umask(0)
os.umask(_UMASK)
TMP_PREFIX = ".partlet-tmp-"


class Store(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes, content_type: str | None = None) -> None: ...
    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool: ...
    def delete(self, key: str) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def list_dirs(self, prefix: str) -> list[str]: ...


class StoreError(Exception):
    """The store could not complete an operation."""


def check_key(key: str) -> str:
    parts = key.split("/")
    if not key or key.startswith("/") or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"invalid store key {key!r}")
    return key


class LocalStore:
    """Stores each key as a file under `root`. Used for previews and tests."""

    def __init__(self, root: Path):
        self.root = root

    def __repr__(self) -> str:
        return f"LocalStore({str(self.root)!r})"

    def _path(self, key: str) -> Path:
        return self.root.joinpath(*check_key(key).split("/"))

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def _write_temp(self, path: Path, data: bytes) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=TMP_PREFIX)
        try:
            # mkstemp creates the file 0600; previews must be readable by any
            # static HTTP server, which may run as another user.
            with os.fdopen(fd, "wb") as f:
                os.fchmod(f.fileno(), 0o666 & ~_UMASK)
                f.write(data)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return tmp

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        path = self._path(key)
        tmp = self._write_temp(path, data)
        try:
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool:
        path = self._path(key)
        tmp = self._write_temp(path, data)
        try:
            os.link(tmp, path)  # atomic, and fails if `path` exists
        except FileExistsError:
            return False
        finally:
            Path(tmp).unlink(missing_ok=True)
        return True

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        keys = (
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(TMP_PREFIX)
        )
        return sorted(k for k in keys if k.startswith(prefix))

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        base = self._path(prefix.rstrip("/"))
        if not base.is_dir():
            return []
        return sorted(p.name for p in base.iterdir() if p.is_dir())


# Read from the environment by R2Config.from_env. The two key variables are
# removed from the environment once read.
R2_ENV = {
    "account_id": "PARTLET_R2_ACCOUNT_ID",
    "access_key_id": "PARTLET_R2_ACCESS_KEY_ID",
    "secret_access_key": "PARTLET_R2_SECRET_ACCESS_KEY",
    "bucket": "PARTLET_R2_BUCKET",
    "endpoint": "PARTLET_R2_ENDPOINT",
}
ACCOUNT_ID_RE = re.compile(r"[0-9a-f]{32}")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class R2Config:
    bucket: str
    endpoint_url: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: MutableMapping[str, str]) -> R2Config:
        """Read the R2 settings from `environ`, removing the two key variables.

        Removing them means git, git-filter-repo and gitleaks, which partlet runs
        as child processes, never inherit the credentials. PARTLET_R2_ENDPOINT
        replaces the endpoint derived from the account ID, for buckets in a
        jurisdiction (https://<account>.eu.r2.cloudflarestorage.com).
        """
        values = {name: environ.get(var, "").strip() for name, var in R2_ENV.items()}
        for name in ("access_key_id", "secret_access_key"):
            environ.pop(R2_ENV[name], None)
        required = ["access_key_id", "secret_access_key", "bucket"]
        if not values["endpoint"]:
            required.append("account_id")
        missing = [R2_ENV[name] for name in required if not values[name]]
        if missing:
            raise StoreError(f"missing R2 settings: {', '.join(missing)}")
        endpoint = values["endpoint"]
        if not endpoint:
            if not ACCOUNT_ID_RE.fullmatch(values["account_id"]):
                raise StoreError(
                    "PARTLET_R2_ACCOUNT_ID must be a 32-character hexadecimal account ID"
                )
            endpoint = f"https://{values['account_id']}.r2.cloudflarestorage.com"
        return cls(
            values["bucket"],
            endpoint,
            values["access_key_id"],
            values["secret_access_key"],
        )


def check_endpoint(url: str) -> str:
    """Refuse endpoints that would send credentials in clear text or elsewhere."""
    parts = urlsplit(url)
    plain_loopback = parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
    if (
        not (parts.scheme == "https" or plain_loopback)
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path not in ("", "/")
        or parts.query
        or parts.fragment
    ):
        raise StoreError(
            f"R2 endpoint must be https://<host> (plain http only on loopback): {url}"
        )
    return url


class R2Store:
    """A bucket in Cloudflare R2, through its S3-compatible API.

    R2 is strongly consistent: a read, list or delete that starts after a
    write returns sees that write. Each put replaces the whole object at once,
    so a reader sees the old object or the new one, never a mix.
    """

    def __init__(
        self, config: R2Config, *, page_size: int = 1000, max_attempts: int = 5
    ):
        import boto3
        from botocore.config import Config

        self.bucket = config.bucket
        self.endpoint_url = check_endpoint(config.endpoint_url)
        self._page_size = page_size
        self._client = boto3.session.Session().client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            config=Config(
                region_name="auto",
                signature_version="s3v4",
                retries={"max_attempts": max_attempts, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
                # Send and check checksums only where the API requires them,
                # whatever this botocore version's default is.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def __repr__(self) -> str:
        return f"R2Store(bucket={self.bucket!r}, endpoint_url={self.endpoint_url!r})"

    def _call(self, what: str, method: str, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(self._client, method)(Bucket=self.bucket, **kwargs)
        except ClientError as e:
            error = e.response.get("Error", {})
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            raise R2ClientError(
                f"R2 {what}: {error.get('Code', 'error')} (HTTP {status}): "
                f"{error.get('Message', '')}",
                code=str(error.get("Code", "")),
                status=status,
            ) from e
        except BotoCoreError as e:
            raise StoreError(f"R2 {what}: {e}") from e

    def get(self, key: str) -> bytes | None:
        check_key(key)
        try:
            response = self._call(f"get {key}", "get_object", Key=key)
        except R2ClientError as e:
            # Only a missing key; NoSuchBucket is also a 404 and must not read
            # as "nothing published".
            if e.code == "NoSuchKey":
                return None
            raise
        return response["Body"].read()

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        check_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        self._call(f"put {key}", "put_object", Key=key, Body=data, **extra)

    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool:
        check_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self._call(
                f"create {key}",
                "put_object",
                Key=key,
                Body=data,
                IfNoneMatch="*",
                **extra,
            )
        except R2ClientError as e:
            # 412: the key exists. 409: another conditional write to it is in
            # progress; either way someone else holds it.
            if e.status in (409, 412):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        check_key(key)
        self._call(f"delete {key}", "delete_object", Key=key)

    def _pages(self, **kwargs) -> Iterator[dict]:
        token = None
        while True:
            extra = {"ContinuationToken": token} if token else {}
            page = self._call(
                f"list {kwargs.get('Prefix', '')}",
                "list_objects_v2",
                MaxKeys=self._page_size,
                **kwargs,
                **extra,
            )
            yield page
            if not page.get("IsTruncated"):
                return
            token = page["NextContinuationToken"]

    def list(self, prefix: str) -> list[str]:
        return sorted(
            obj["Key"]
            for page in self._pages(Prefix=prefix)
            for obj in page.get("Contents", [])
        )

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        return sorted(
            common["Prefix"][len(prefix) :].rstrip("/")
            for page in self._pages(Prefix=prefix, Delimiter="/")
            for common in page.get("CommonPrefixes", [])
        )


class R2ClientError(StoreError):
    """R2 answered a request with an error."""

    def __init__(self, message: str, *, code: str, status: int | None):
        super().__init__(message)
        self.code = code
        self.status = status
```

Notes for the reviewer:

- Paging: `list_objects_v2` returns at most `MaxKeys` (R2: 1000) keys per call; `_pages` follows `NextContinuationToken` until `IsTruncated` is false. The sweep and `unpublish` depend on seeing every key.
- `get` returns `None` only for `NoSuchKey`. `NoSuchBucket` is also an HTTP 404, and reading it as "nothing published" would turn a misconfigured bucket into a first publication.
- Retries: botocore's standard mode retries throttling, 5xx and connection errors up to `max_attempts` with backoff. Every operation here is safe to repeat.
- The two `*_checksum_*` settings make botocore add checksums only where an operation requires them, so behaviour does not change with botocore's defaults. The current Cloudflare boto3 example does not mention them; they are a defensive choice, recorded in docs/DECISIONS.md (Task 14).
- `boto3` is imported inside `R2Store.__init__`, so `partlet build` and the tests that do not touch R2 do not pay for importing it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_r2_store.py tests/test_lock.py tests/test_store.py -v`
Expected: all PASS. moto's request log lines in captured output are expected.

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/partlet/store.py tests/conftest.py tests/helpers.py tests/test_lock.py tests/test_r2_store.py
git commit -m "Add the R2 store over the S3-compatible API"
```

---

### Task 7: A publish interrupted at any single write

Queue area `[PUBLISHER]`. Test-only, unless it finds a bug.

**Files:**
- Test: `tests/test_publish_interrupted.py`

**Interfaces:**
- Consumes: `publish_all`, `LocalStore`, `StoreError` (Task 6), `read_state`, `helpers.export_tip`.
- Produces: nothing new.

The orphan-sweep branch tests interruptions at chosen keys. This test fails the publish at every put and delete in turn, so a change to the upload order that leaves a pointer ahead of its objects fails here even if nobody thought to test that key. It takes about 40 seconds.

- [ ] **Step 1: Write the test**

`tests/test_publish_interrupted.py`:

```python
"""A publish that dies at any single write or delete never breaks what is live."""

import json
import shutil

from helpers import export_tip

from partlet.archive import ARCHIVE_FORMATS
from partlet.gitstatic import read_state
from partlet.gitutil import git, git_out
from partlet.manifest import parse_manifest
from partlet.publish import publish_all
from partlet.store import LocalStore, StoreError


class FlakyStore(LocalStore):
    """Counts puts and deletes, and fails operation number `fail_at` (from 1)."""

    def __init__(self, root, fail_at=None):
        super().__init__(root)
        self.fail_at = fail_at
        self.ops = 0

    def _tick(self, what):
        self.ops += 1
        if self.ops == self.fail_at:
            raise StoreError(f"injected failure at operation {self.ops}: {what}")

    def put(self, key, data, content_type=None):
        self._tick(f"put {key}")
        super().put(key, data, content_type)

    def delete(self, key):
        self._tick(f"delete {key}")
        super().delete(key)


def manifest(approved):
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""")


def publish(mono, tmp_path, store, approved):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    try:
        (result,) = publish_all(mono.path, manifest(approved), store, work)
    except StoreError:
        return None  # the failure hit the site index, after the project
    return result


def assert_live_state_complete(store):
    """Every key the live pointers name exists."""
    prefix = "s/p/foo"
    for pack in read_state(store, f"{prefix}/git").packs:
        for ext in ("pack", "idx"):
            assert store.get(f"{prefix}/git/objects/pack/{pack}.{ext}") is not None
    current = json.loads(store.get(f"{prefix}/current"))
    assert store.get(f"{prefix}/site/{current['build']}/index.html") is not None
    for fmt in ARCHIVE_FORMATS:
        assert store.get(f"{prefix}/archive/{current['tip']}.{fmt}") is not None


def test_failure_at_every_operation_leaves_a_cloneable_repo_and_a_retry_recovers(
    mono, tmp_path, serve
):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    base = tmp_path / "base"
    store = LocalStore(base)
    for n in (2, 3):  # two earlier publishes, so the sweep has keys to delete
        assert publish(mono, tmp_path, store, approved).status == "published"
        mono.write("foo/README.md", f"# Foo {n}\n")
        mono.commit(f"c{n}")
    old_tip = read_state(store, "s/p/foo/git").tip
    new_tip = export_tip(mono, tmp_path)

    counting = FlakyStore(tmp_path / "count")
    shutil.copytree(base, counting.root)
    assert publish(mono, tmp_path, counting, approved).status == "published"
    assert counting.ops > 10

    for fail_at in range(1, counting.ops + 1):
        root = tmp_path / f"case-{fail_at}"
        shutil.copytree(base, root)
        publish(mono, tmp_path, FlakyStore(root, fail_at), approved)
        after_failure = LocalStore(root)
        assert_live_state_complete(after_failure)
        clone = tmp_path / f"clone-{fail_at}"
        with serve(root) as url:
            git("clone", "-q", f"{url}/s/p/foo/git", str(clone), cwd=tmp_path)
        assert git_out("rev-parse", "HEAD", cwd=clone) in (old_tip, new_tip)

        retry = publish(mono, tmp_path, after_failure, approved)
        assert retry.status in ("published", "unchanged"), (fail_at, retry)
        assert_live_state_complete(after_failure)
        assert read_state(after_failure, "s/p/foo/git").tip == new_tip
        index = json.loads(after_failure.get("s/index.json"))
        assert [(p["name"], p["tip"]) for p in index] == [("foo", new_tip)]
        with serve(root) as url:
            git("pull", "-q", "--ff-only", f"{url}/s/p/foo/git", "main", cwd=clone)
        assert git_out("rev-parse", "HEAD", cwd=clone) == new_tip
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/test_publish_interrupted.py -v`
Expected: PASS on the code from the orphan-sweep branch. If a case fails, the assertion names the operation; find out why that order leaves a pointer ahead of its object (root cause first) and fix `publish.py`, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/test_publish_interrupted.py
git commit -m "Test a publish interrupted at every write and its retry"
```

---

### Task 8: `partlet publish`, `build --scan` and the step summary

Queue area `[PUBLISHER]`.

**Files:**
- Create: `src/partlet/summary.py`
- Modify: `src/partlet/publish.py`, `src/partlet/cli.py`
- Test: `tests/test_cli_publish.py`, `tests/test_summary.py`

**Interfaces:**
- Consumes: Tasks 3 to 6.
- Produces:
  - `class CheckoutError(Exception)`, `check_checkout(repo: Path, branch: str, manifest_path: Path) -> None`
  - `summary.REASON_LIMIT = 300`, `summary_markdown(title: str, results: list[ProjectResult], versions: dict[str, str]) -> str`, `write_summary(path: Path | None, text: str) -> None`
  - `partlet build --out DIR [--scan] [--summary FILE]` and `partlet publish [--repo DIR] [--manifest FILE] [--summary FILE]`; `--summary` defaults to `$GITHUB_STEP_SUMMARY`
  - exit codes: 0 all good; 1 a project failed, the lock was held or the store failed; 2 configuration refused (manifest, checkout, tools, missing credentials)

- [ ] **Step 1: Write the failing tests**

`tests/test_summary.py`:

```python
from partlet.publish import ProjectResult
from partlet.summary import REASON_LIMIT, summary_markdown, write_summary


def test_table_rows_and_tools():
    text = summary_markdown(
        "Partlet publish",
        [
            ProjectResult("foo", "published", "a" * 40, "first publication"),
            ProjectResult("bar", "skipped", None, "not approved"),
        ],
        {"partlet": "0.1.0", "gitleaks": "8.30.1"},
    )
    assert "| foo | published | `aaaaaaaaaaaa` | first publication |" in text
    assert "| bar | skipped |  | not approved |" in text
    assert "Tools: partlet 0.1.0, gitleaks 8.30.1" in text


def test_reasons_cannot_break_the_table_or_inject_html():
    reason = "line one\nline | two <script>x</script> " + "y" * 400
    text = summary_markdown("T", [ProjectResult("foo", "failed", None, reason)], {})
    (row,) = [line for line in text.splitlines() if line.startswith("| foo")]
    assert "line one line \\| two &lt;script&gt;" in row
    assert "<script>" not in text
    assert row.count(" | ") == 3
    assert len(row) < REASON_LIMIT + 100


def test_write_summary_appends(tmp_path):
    path = tmp_path / "summary.md"
    write_summary(path, "one")
    write_summary(path, "two")
    write_summary(None, "ignored")
    assert path.read_text() == "one\ntwo\n"
```

`tests/test_cli_publish.py`:

```python
import json
import os

import pytest
from helpers import FAKE_R2_SECRET, export_tip, mirror_store

from partlet.cli import main
from partlet.gitutil import git
from partlet.store import R2Store

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"


def write_manifest(mono, approved, extra=""):
    mono.write(
        "partlet.toml",
        f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
{extra}
""",
    )
    mono.commit("manifest")  # touches nothing under foo/: the export tip stays


@pytest.fixture
def approved(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    tip = export_tip(mono, tmp_path)
    write_manifest(mono, tip)
    return tip


@pytest.fixture
def publish(tmp_path, monkeypatch, request):
    """Run `partlet publish` with credentials for the moto bucket, if any.

    The keys are set before every run, because each run removes them from
    the environment.
    """

    def run(mono, secret=None):
        if "r2_env" in request.fixturenames:
            config = request.getfixturevalue("r2_env")
            monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", config.access_key_id)
            monkeypatch.setenv(
                "PARTLET_R2_SECRET_ACCESS_KEY", secret or config.secret_access_key
            )
        summary = tmp_path / f"summary-{len(list(tmp_path.glob('summary-*')))}.md"
        code = main(["publish", "--repo", str(mono.path), "--summary", str(summary)])
        return code, summary.read_text() if summary.exists() else ""

    return run


def test_publish_to_r2_then_clone_and_pull(
    mono, tmp_path, r2_env, approved, serve, publish
):
    code, summary = publish(mono)
    assert code == 0
    assert "| foo | published |" in summary
    assert "gitleaks 8.30.1" in summary
    store = R2Store(r2_env)
    assert store.get("s/lock") is None
    mirror_store(store, tmp_path / "site-1")
    clone = tmp_path / "clone"
    with serve(tmp_path / "site-1") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(clone), cwd=tmp_path)

    mono.write("foo/b.txt", "two\n")
    mono.commit("c2")
    assert publish(mono)[0] == 0
    mirror_store(store, tmp_path / "site-2")
    with serve(tmp_path / "site-2") as base:
        git("pull", "-q", "--ff-only", f"{base}/s/p/foo/git", "main", cwd=clone)
    assert (clone / "b.txt").read_text() == "two\n"


def test_publish_removes_the_keys_from_the_environment(
    mono, tmp_path, r2_env, approved, publish
):
    assert publish(mono)[0] == 0
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in os.environ
    assert "PARTLET_R2_ACCESS_KEY_ID" not in os.environ


def test_secret_never_reaches_output(
    mono, tmp_path, r2_env, approved, capsys, monkeypatch, publish
):
    assert publish(mono)[0] == 0
    # And a failing run, against a bucket that does not exist.
    monkeypatch.setenv("PARTLET_R2_BUCKET", "partlet-no-such-bucket")
    code, summary = publish(mono, secret=FAKE_R2_SECRET)
    assert code == 1
    out = capsys.readouterr()
    for text in (out.out, out.err, summary):
        assert FAKE_R2_SECRET not in text


def test_missing_credentials(mono, tmp_path, approved, capsys, publish):
    assert publish(mono)[0] == 2
    assert "PARTLET_R2_BUCKET" in capsys.readouterr().err


def test_refuses_a_checkout_of_another_branch(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    git("checkout", "-q", "-b", "feature", cwd=mono.path)
    mono.write("other.txt", "x\n")
    mono.commit("feature work")
    assert publish(mono)[0] == 2
    assert "HEAD is" in capsys.readouterr().err


def test_refuses_without_a_local_publishing_branch(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    # What a pull_request checkout looks like: detached HEAD, no refs/heads/main.
    git("checkout", "-q", "--detach", cwd=mono.path)
    git("branch", "-q", "-D", "main", cwd=mono.path)
    assert publish(mono)[0] == 2
    assert "branch 'main' not found" in capsys.readouterr().err


def test_refuses_an_uncommitted_manifest_edit(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    text = (mono.path / "partlet.toml").read_text()
    (mono.path / "partlet.toml").write_text(text + "\n# edited\n")
    assert publish(mono)[0] == 2
    assert "differs from the version committed" in capsys.readouterr().err


def test_ci_enforces_the_approval_pin_and_fast_forward(
    mono, tmp_path, r2_env, approved, publish
):
    assert publish(mono)[0] == 0

    # Rewrite the monorepo's history, so foo's published tip is no longer an
    # ancestor of its export. The manifest still carries the old approval.
    git("checkout", "-q", "--orphan", "rewritten", cwd=mono.path)
    mono.write("foo/README.md", "# Foo, rewritten\n")
    mono.commit("c1 again")
    git("branch", "-q", "-M", "main", cwd=mono.path)
    code, summary = publish(mono)
    assert code == 1
    assert "| foo | failed |" in summary
    assert "history rewrite" in summary


def test_secret_blocks_the_publish(mono, tmp_path, r2_env, publish):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    write_manifest(mono, export_tip(mono, tmp_path))
    code, summary = publish(mono)
    assert code == 1
    assert "secret scan: 1 finding(s)" in summary
    assert FAKE_TOKEN not in summary
    assert R2Store(r2_env).list("s/p/") == []


def test_a_held_lock_stops_the_publish(
    mono, tmp_path, r2_env, approved, capsys, publish
):
    held = json.dumps({"holder": "another run", "since": "2026-10-17T00:00:00+00:00"})
    R2Store(r2_env).put("s/lock", held.encode())
    code, _ = publish(mono)
    assert code == 1
    assert "locked by another run" in capsys.readouterr().err
    assert R2Store(r2_env).list("s/p/") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_summary.py tests/test_cli_publish.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.summary'` and `argparse` errors (`invalid choice: 'publish'`).

- [ ] **Step 3: Implement the checkout check**

In `src/partlet/publish.py`, change the gitutil import to `from partlet.gitutil import GitError, git, git_out` and add above `write_site_index`:

```python
class CheckoutError(Exception):
    """The monorepo checkout is not what `partlet publish` must run from."""


def check_checkout(repo: Path, branch: str, manifest_path: Path) -> None:
    """Refuse unless HEAD is the tip of the local publishing branch and the
    manifest is exactly as committed there.

    The export reads `refs/heads/<branch>` while the manifest (with its
    approval pins) comes from the working tree, so both must name the same
    commit: otherwise a run on another branch, or a step that edits the
    manifest, could publish with pins that were never committed.
    """
    try:
        head = git_out("rev-parse", "--verify", "HEAD^{commit}", cwd=repo)
        toplevel = Path(git_out("rev-parse", "--show-toplevel", cwd=repo))
    except GitError as e:
        raise CheckoutError(f"{repo} is not a git checkout: {e}") from e
    try:
        tip = git_out(
            "rev-parse", "--verify", f"refs/heads/{branch}^{{commit}}", cwd=repo
        )
    except GitError:
        raise CheckoutError(
            f"branch {branch!r} not found in {repo}: publishing needs a local "
            f"refs/heads/{branch} (the Partlet action creates it from origin/{branch})"
        ) from None
    if head != tip:
        raise CheckoutError(
            f"HEAD is {head[:12]} but {branch} is at {tip[:12]}; partlet publish "
            f"runs from a checkout of the tip of {branch}"
        )
    try:
        rel = manifest_path.resolve().relative_to(toplevel.resolve())
    except ValueError:
        raise CheckoutError(f"{manifest_path} is not inside {toplevel}") from None
    try:
        committed = git("show", f"{tip}:{rel.as_posix()}", cwd=repo).stdout
    except GitError:
        raise CheckoutError(f"{rel} is not committed on {branch}") from None
    if manifest_path.read_bytes() != committed:
        raise CheckoutError(f"{rel} differs from the version committed on {branch}")
```

`partlet build` does not call this: previews run from any working tree.

- [ ] **Step 4: Implement the summary and the CLI**

`src/partlet/summary.py`:

```python
"""The GitHub Actions step summary: one table row per project."""

from __future__ import annotations

from pathlib import Path

from partlet.publish import ProjectResult

REASON_LIMIT = 300


def _cell(text: str) -> str:
    text = " ".join(text.split())
    if len(text) > REASON_LIMIT:
        text = text[: REASON_LIMIT - 3] + "..."
    for raw, escaped in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ("|", "\\|")):
        text = text.replace(raw, escaped)
    return text


def summary_markdown(
    title: str, results: list[ProjectResult], versions: dict[str, str]
) -> str:
    lines = [
        f"## {title}",
        "",
        "| Project | Status | Tip | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        tip = f"`{r.tip[:12]}`" if r.tip else ""
        lines.append(f"| {_cell(r.name)} | {r.status} | {tip} | {_cell(r.reason)} |")
    if not results:
        lines.append("| (no projects) | | | |")
    tools = ", ".join(f"{name} {version}" for name, version in versions.items())
    lines += ["", f"Tools: {_cell(tools)}", ""]
    return "\n".join(lines)


def write_summary(path: Path | None, text: str) -> None:
    """Append to the step summary file, if there is one."""
    if path is not None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
```

Replace `src/partlet/cli.py` with:

```python
"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
from pathlib import Path

from partlet.lock import LockError, describe_holder, store_lock
from partlet.manifest import Manifest, ManifestError, load_manifest
from partlet.publish import CheckoutError, check_checkout, publish_all
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

    return parser


def _error(message: object) -> int:
    print(f"partlet: {message}", file=sys.stderr)
    return 2


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
    except (LockError, StoreError) as e:
        print(f"partlet: {e}", file=sys.stderr)
        write_summary(summary, summary_markdown(title, [], versions) + f"\nFailed: {e}")
        return 1
    for r in results:
        print(f"{r.name:24} {r.status:10} {(r.tip or '')[:12]:12} {r.reason}")
    write_summary(summary, summary_markdown(title, results, versions))
    return 1 if any(r.status == "failed" for r in results) else 0


def _build(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    try:
        manifest = load_manifest(_manifest_path(args))
        tools = check_tools(gitleaks=args.scan)
    except (ManifestError, ToolError) as e:
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
        check_checkout(repo, manifest.site.branch, manifest_path)
        tools = check_tools(gitleaks=True)
        store = R2Store(config)
    except (StoreError, ManifestError, CheckoutError, ToolError) as e:
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


def _exit_on_sigterm(signum, frame):
    # A cancelled CI job gets SIGTERM; exiting this way runs the `finally`
    # blocks, so the lock is released.
    raise SystemExit(128 + signum)


COMMANDS = {
    "build": _build,
    "publish": _publish,
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
```

Points to check: `_publish` reads the credentials before anything else, so they are out of the environment before `check_checkout` starts git; the lock wraps the whole of `publish_all`, including the site index; `main` puts the previous SIGTERM handler back, so tests that call `main` leave pytest's handler alone.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_summary.py tests/test_cli_publish.py tests/test_cli.py -v`
Expected: all PASS.

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`.

- [ ] **Step 6: Commit**

```bash
git add src/partlet/summary.py src/partlet/publish.py src/partlet/cli.py tests/test_summary.py tests/test_cli_publish.py
git commit -m "Add partlet publish, build --scan and the step summary"
```

---

### Task 9: `partlet unpublish` and `partlet unlock`

Queue area `[PUBLISHER]`.

**Files:**
- Modify: `src/partlet/publish.py`, `src/partlet/cli.py`
- Test: `tests/test_unpublish.py`

**Interfaces:**
- Consumes: Tasks 5, 6 and 8.
- Produces:
  - `unpublish_project(store: Store, site: Site, name: str) -> int` (number of keys removed; `ValueError` for an invalid name; `StoreError` if keys remain)
  - `partlet unpublish NAME [--repo] [--manifest] [--out DIR] [--yes]` and `partlet unlock [--repo] [--manifest] [--out DIR] [--yes]`; without `--out` both act on R2, configured from `PARTLET_R2_*`

`unpublish` is run by the user, never automatically (spec, "Other commands"). It needs the same R2 credentials as CI. Run it from a shell that has them, while no publish is running. If one is running, the lock makes `unpublish` fail rather than race it.

- [ ] **Step 1: Write the failing tests**

`tests/test_unpublish.py`:

```python
import json

import pytest
from helpers import export_tip

from partlet.cli import main
from partlet.manifest import parse_manifest
from partlet.publish import publish_all, unpublish_project
from partlet.store import LocalStore, R2Store

SITE = """
[site]
source = "s"
base_url = "https://partlet.example"
"""


@pytest.fixture(params=["local", "r2"])
def published(request, mono, tmp_path):
    """foo and foobar published; returns the store and foobar's keys."""
    if request.param == "local":
        store = LocalStore(tmp_path / "out")
    else:
        store = R2Store(request.getfixturevalue("r2_config"), page_size=2)
    mono.write("foo/a.txt", "a\n")
    mono.write("foobar/b.txt", "b\n")
    mono.commit("c1")
    tips = {name: export_tip(mono, tmp_path, name) for name in ("foo", "foobar")}
    m = parse_manifest(
        SITE
        + "".join(
            f'[projects.{n}]\npath = "{n}"\napproved = "{t}"\n' for n, t in tips.items()
        )
    )
    results = publish_all(mono.path, m, store, tmp_path / "work")
    assert [r.status for r in results] == ["published", "published"]
    return store, {k: store.get(k) for k in store.list("s/p/foobar/")}


def test_unpublish_removes_every_key_and_the_index_entry(published):
    store, foobar = published
    site = parse_manifest(SITE).site
    assert unpublish_project(store, site, "foo") > 5
    assert store.list("s/p/foo/") == []
    assert {k: store.get(k) for k in store.list("s/p/foobar/")} == foobar
    assert [p["name"] for p in json.loads(store.get("s/index.json"))] == ["foobar"]
    assert b'href="/foo"' not in store.get("s/index.html")
    assert b'href="/foobar"' in store.get("s/index.html")


def test_unpublish_resumes_after_an_interruption(published):
    store, _ = published
    site = parse_manifest(SITE).site

    class DiesAfterThreeDeletes:
        def __init__(self, inner):
            self.inner, self.deletes = inner, 0

        def delete(self, key):
            self.deletes += 1
            if self.deletes > 3:
                raise OSError("interrupted")
            self.inner.delete(key)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with pytest.raises(OSError):
        unpublish_project(DiesAfterThreeDeletes(store), site, "foo")
    assert store.get("s/p/foo/current") is None
    assert [p["name"] for p in json.loads(store.get("s/index.json"))] == ["foobar"]
    assert store.list("s/p/foo/")
    unpublish_project(store, site, "foo")
    assert store.list("s/p/foo/") == []


@pytest.mark.parametrize("name", ["", "../x", "foo/", "Foo", "foo.git"])
def test_invalid_names_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        unpublish_project(LocalStore(tmp_path), parse_manifest(SITE).site, name)


def write_manifest(mono, body=""):
    mono.write("partlet.toml", SITE + body)


def test_cli_refuses_a_project_still_approved(mono, tmp_path, capsys):
    write_manifest(mono, f'[projects.foo]\npath = "foo"\napproved = "{"a" * 40}"\n')
    args = ["unpublish", "foo", "--repo", str(mono.path), "--out", str(tmp_path)]
    assert main([*args, "--yes"]) == 2
    assert "still approved" in capsys.readouterr().err


def test_cli_asks_before_deleting(mono, tmp_path, monkeypatch):
    write_manifest(mono)
    out = tmp_path / "out"
    LocalStore(out).put("s/p/foo/current", b"{}")
    args = ["unpublish", "foo", "--repo", str(mono.path), "--out", str(out)]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(args) == 1
    assert LocalStore(out).get("s/p/foo/current") == b"{}"
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main(args) == 0
    assert LocalStore(out).list("s/p/foo/") == []
    assert LocalStore(out).get("s/lock") is None


@pytest.mark.parametrize("published", ["r2"], indirect=True)
def test_cli_unpublish_from_r2(mono, tmp_path, r2_env, published):
    store, _ = published
    write_manifest(mono)
    assert main(["unpublish", "foo", "--repo", str(mono.path), "--yes"]) == 0
    assert store.list("s/p/foo/") == []


def test_cli_unlock(mono, tmp_path, monkeypatch, capsys):
    write_manifest(mono)
    out = tmp_path / "out"
    LocalStore(out).put("s/lock", b'{"holder": "dead run", "since": "then"}')
    args = ["unlock", "--repo", str(mono.path), "--out", str(out)]
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main(args) == 0
    assert "locked by dead run" in capsys.readouterr().out
    assert LocalStore(out).get("s/lock") is None
    assert main(args) == 0
    assert "not locked" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_unpublish.py -v`
Expected: FAIL with `ImportError: cannot import name 'unpublish_project' from 'partlet.publish'`.

- [ ] **Step 3: Implement**

In `src/partlet/publish.py`, change the imports to `from partlet.manifest import NAME_RE, Manifest, Project, Site` and `from partlet.store import Store, StoreError`, and add above `publish_all`:

```python
def unpublish_project(store: Store, site: Site, name: str) -> int:
    """Delete every key under `<source>/p/<name>/` and rebuild the site index.

    `current` goes first, so the Worker stops serving the project and the
    rebuilt index leaves it out even if the run dies part way; running again
    finishes the job. Returns the number of keys that were there.
    """
    if not NAME_RE.fullmatch(name) or name.endswith(".git"):
        raise ValueError(f"invalid project name {name!r}")
    prefix = f"{project_prefix(site.source, name)}/"
    keys = store.list(prefix)
    store.delete(f"{prefix}current")
    write_site_index(store, site)
    for key in keys:
        store.delete(key)
    left = store.list(prefix)
    if left:
        raise StoreError(f"{len(left)} keys remain under {prefix}, e.g. {left[0]}")
    return len(keys)
```

The trailing `/` in `prefix` is what keeps `foobar` safe when unpublishing `foo`, and the name check keeps `""` or `../x` from widening it.

In `src/partlet/cli.py`:

1. Change the imports to:

```python
from partlet.lock import LockError, describe_holder, lock_key, read_lock, store_lock
from partlet.manifest import NAME_RE, Manifest, ManifestError, load_manifest
from partlet.publish import (
    CheckoutError,
    check_checkout,
    project_prefix,
    publish_all,
    unpublish_project,
)
```

2. In `_parser`, before `return parser`, add:

```python
    unpublish = sub.add_parser(
        "unpublish", help="delete one project's keys and rebuild the site index"
    )
    unpublish.add_argument("name", help="project name")
    _repo_args(unpublish)
    unpublish.add_argument(
        "--out", type=Path, help="act on this local directory instead of R2"
    )
    unpublish.add_argument("--yes", action="store_true", help="do not ask")

    unlock = sub.add_parser(
        "unlock", help="remove the publish lock left behind by a run that died"
    )
    _repo_args(unlock)
    unlock.add_argument(
        "--out", type=Path, help="act on this local directory instead of R2"
    )
    unlock.add_argument("--yes", action="store_true", help="do not ask")
```

3. Add after `_error`:

```python
def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False
```

4. Add before `_exit_on_sigterm`:

```python
def _store_for(args: argparse.Namespace) -> Store:
    if args.out is not None:
        return LocalStore(args.out)
    return R2Store(R2Config.from_env(os.environ))


def _unpublish(args: argparse.Namespace) -> int:
    name = args.name
    if not NAME_RE.fullmatch(name) or name.endswith(".git"):
        return _error(f"invalid project name {name!r}")
    manifest_path = _manifest_path(args)
    try:
        store = _store_for(args)
        manifest = load_manifest(manifest_path)
    except (StoreError, ManifestError) as e:
        return _error(e)
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
    except (LockError, StoreError) as e:
        print(f"partlet: {e}", file=sys.stderr)
        return 1
    print(f"partlet: removed {removed} keys under {prefix} and rebuilt the index")
    return 0


def _unlock(args: argparse.Namespace) -> int:
    try:
        store = _store_for(args)
        source = load_manifest(_manifest_path(args)).site.source
        held = read_lock(store, source)
    except (StoreError, ManifestError) as e:
        return _error(e)
    if held is None:
        print(f"partlet: {source} is not locked")
        return 0
    print(
        f"partlet: {source} is locked by {held.get('holder')} since {held.get('since')}"
    )
    question = "Remove the lock? Only do this if that run is not running. [y/N] "
    if not args.yes and not _confirm(question):
        return 1
    try:
        store.delete(lock_key(source))
    except StoreError as e:
        print(f"partlet: {e}", file=sys.stderr)
        return 1
    print("partlet: lock removed")
    return 0
```

5. Add `"unpublish": _unpublish,` and `"unlock": _unlock,` to `COMMANDS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_unpublish.py tests/test_cli.py tests/test_cli_publish.py -v`
Expected: all PASS.

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`.

- [ ] **Step 5: Commit**

```bash
git add src/partlet/publish.py src/partlet/cli.py tests/test_unpublish.py
git commit -m "Add partlet unpublish and partlet unlock"
```

---

### Task 10: Edit the manifest with tomlkit

Queue area `[PUBLISHER]`.

**Files:**
- Modify: `pyproject.toml`, `src/partlet/manifest.py`
- Test: `tests/test_manifest_edit.py`

**Interfaces:**
- Consumes: `parse_manifest`, `PROJECT_KEYS` (plan 1).
- Produces: `set_project_fields(path: Path, name: str, fields: dict[str, str]) -> None` (raises `ManifestError`, leaving the file untouched, for an unknown project or key or a result that would not load)

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add `"tomlkit>=0.13",` to `dependencies`. Run `bash scripts/setup.sh`.

- [ ] **Step 2: Write the failing tests**

`tests/test_manifest_edit.py`:

```python
import pytest

from partlet.manifest import ManifestError, load_manifest, set_project_fields

TEXT = """# Partlet manifest
[site]
source = "s"   # key prefix
base_url = "https://x"

[projects.foo]
path = "foo"  # where it lives
# approved by partlet review
approved = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[projects.bar]
path = "bar"
"""


def test_replaces_and_adds_fields_keeping_comments(tmp_path):
    path = tmp_path / "partlet.toml"
    path.write_text(TEXT)
    set_project_fields(path, "foo", {"approved": "b" * 40})
    set_project_fields(
        path, "bar", {"approved": "c" * 40, "allow_rewrite_of": "d" * 40}
    )
    text = path.read_text()
    assert text.startswith("# Partlet manifest\n")
    assert 'source = "s"   # key prefix' in text
    assert 'path = "foo"  # where it lives\n# approved by partlet review\n' in text
    m = load_manifest(path)
    assert m.projects["foo"].approved == "b" * 40
    assert m.projects["bar"].approved == "c" * 40
    assert m.projects["bar"].allow_rewrite_of == "d" * 40


def test_inline_project_table(tmp_path):
    path = tmp_path / "partlet.toml"
    path.write_text(
        '[site]\nsource = "s"\nbase_url = "x"\n[projects]\nfoo = { path = "foo" }\n'
    )
    set_project_fields(path, "foo", {"approved": "e" * 40})
    assert load_manifest(path).projects["foo"].approved == "e" * 40


@pytest.mark.parametrize(
    "name, fields, message",
    [
        ("missing", {"approved": "b" * 40}, "not in"),
        ("foo", {"colour": "red"}, "not a project key"),
        ("foo", {"approved": "short"}, "40-character"),
    ],
)
def test_refuses_bad_edits_and_leaves_the_file(tmp_path, name, fields, message):
    path = tmp_path / "partlet.toml"
    path.write_text(TEXT)
    with pytest.raises(ManifestError, match=message):
        set_project_fields(path, name, fields)
    assert path.read_text() == TEXT
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_manifest_edit.py -v`
Expected: FAIL with `ImportError: cannot import name 'set_project_fields'`.

- [ ] **Step 4: Implement**

Append to `src/partlet/manifest.py`:

```python
def set_project_fields(path: Path, name: str, fields: dict[str, str]) -> None:
    """Set string fields of `[projects.<name>]` in the manifest at `path`.

    Edits through tomlkit, so comments and layout survive, and refuses to
    write a manifest that would not load.
    """
    import tomlkit

    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.ParseError) as e:
        raise ManifestError(f"cannot edit {path}: {e}") from e
    projects = doc.get("projects")
    if projects is None or name not in projects:
        raise ManifestError(f"project {name!r} is not in {path}")
    table = projects[name]
    for key, value in fields.items():
        if key not in PROJECT_KEYS:
            raise ManifestError(f"{key!r} is not a project key")
        table[key] = value
    text = tomlkit.dumps(doc)
    parse_manifest(text)
    tmp = path.with_name(f".{path.name}.partlet-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_manifest_edit.py tests/test_manifest.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/partlet/manifest.py tests/test_manifest_edit.py
git commit -m "Edit partlet.toml with tomlkit, keeping comments and layout"
```

---

### Task 11: `partlet review`

Queue area `[PUBLISHER]`.

**Files:**
- Create: `src/partlet/review.py`
- Modify: `src/partlet/cli.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `export_project`, `is_ancestor`, `Scanner`, `check_tools`, `set_project_fields`.
- Produces:
  - `class ReviewError(Exception)`, `@dataclass(frozen=True) class EarlierLocation(location: str, renames: tuple[str, ...])`, `@dataclass(frozen=True) class Report(...)` with `render() -> str`
  - `history_paths(repo) -> tuple[tuple[str, bool], ...]`, `large_files(repo, cap=SIZE_CAP) -> tuple[tuple[str, int], ...]`, `earlier_locations(monorepo, branch, project) -> tuple[EarlierLocation, ...]`
  - `fetch_published_tip(base_url: str, name: str, timeout: float = 10) -> str | None` (reads `<base_url>/<name>/info/refs` from the public site; `None` on 404)
  - `build_report(monorepo, manifest, project, workdir, scanner, published_tip) -> Report`
  - `run_review(monorepo, manifest_path, name, workdir, *, scanner, published_tip, allow_rewrite, confirm, pager) -> int`
  - `partlet review NAME [--repo] [--manifest] [--allow-rewrite] [--published-tip SHA|none]`

What the report covers, from the spec: every path that ever existed in the export, with deleted paths marked; files over the 1 MiB cap anywhere in history; distinct authors and committers; the commit count and full log, through a pager; gitleaks findings over the full export history, with fingerprints for `.gitleaksignore`; and undeclared earlier locations, found as renames in the monorepo's history from outside `path` and `previous_paths` into them. The published tip comes from the public site, so `review` needs no R2 credentials.

Approval is refused while there are findings (CI would refuse the publish anyway), and for a tip that does not fast-forward from the published one unless `--allow-rewrite` is given. In that case `allow_rewrite_of` is written as well.

- [ ] **Step 1: Write the failing tests**

`tests/test_review.py`:

```python
import pytest
from helpers import export_tip

from partlet.cli import main
from partlet.gitutil import git_out
from partlet.manifest import load_manifest
from partlet.review import ReviewError, fetch_published_tip, run_review
from partlet.scan import Scanner, check_gitleaks
from partlet.site.tree import SIZE_CAP

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"

MANIFEST = """# the manifest
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "tools/foo"  # moved here from scripts/foo
"""


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


@pytest.fixture
def moved(mono):
    """foo lived in scripts/foo, moved to tools/foo; one file was deleted."""
    mono.write("scripts/foo/a.txt", "a\n")
    mono.write("scripts/foo/old.txt", "old\n")
    mono.commit("c1")
    mono.rm("scripts/foo/old.txt")
    mono.commit("drop old")
    mono.mv("scripts/foo", "tools/foo")
    mono.write("tools/foo/big.bin", b"\0" * (SIZE_CAP + 1))
    mono.commit("move")
    mono.write("partlet.toml", MANIFEST)
    mono.commit("manifest")
    return mono


def review(mono, tmp_path, gitleaks, answer="y", published=None, allow_rewrite=False):
    pages = []
    code = run_review(
        mono.path,
        mono.path / "partlet.toml",
        "foo",
        tmp_path / f"review-{len(list(tmp_path.glob('review-*')))}",
        scanner=Scanner(gitleaks, mono.path),
        published_tip=published,
        allow_rewrite=allow_rewrite,
        confirm=lambda prompt: answer == "y",
        pager=pages.append,
    )
    return code, pages[0]


def test_report_and_approval(moved, tmp_path, gitleaks):
    code, page = review(moved, tmp_path, gitleaks)
    assert code == 0
    tip = load_manifest(moved.path / "partlet.toml").projects["foo"].approved
    assert f"Export tip:    {tip} (1 commits)" in page
    assert "Published tip: none (first publication)" in page
    assert "    a.txt" in page
    assert f"  {SIZE_CAP + 1:>12} big.bin" in page
    assert "Test Author <author@example.com>" in page
    assert "0 finding(s)" in page
    assert "scripts/foo: consider adding it to previous_paths" in page
    assert "scripts/foo/a.txt -> tools/foo/a.txt" in page
    text = (moved.path / "partlet.toml").read_text()
    assert text.startswith("# the manifest\n")
    assert 'path = "tools/foo"  # moved here from scripts/foo' in text


def test_deleted_paths_are_marked(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.write("foo/gone.txt", "x\n")
    mono.commit("c1")
    mono.rm("foo/gone.txt")
    mono.commit("c2")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    _, page = review(mono, tmp_path, gitleaks, answer="n")
    assert "  D gone.txt" in page
    assert "    a.txt" in page


def test_declining_leaves_the_manifest(moved, tmp_path, gitleaks):
    before = (moved.path / "partlet.toml").read_text()
    code, _ = review(moved, tmp_path, gitleaks, answer="n")
    assert code == 1
    assert (moved.path / "partlet.toml").read_text() == before


def test_findings_block_approval(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    code, page = review(mono, tmp_path, gitleaks)
    assert code == 1
    assert "github-pat in config.py:1" in page
    assert "fingerprint:" in page
    assert FAKE_TOKEN not in page
    assert load_manifest(mono.path / "partlet.toml").projects["foo"].approved is None


def test_rewrite_needs_allow_rewrite(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    unrelated = "b" * 40  # a published tip that is not in this history
    code, page = review(mono, tmp_path, gitleaks, published=unrelated)
    assert code == 1
    assert "this is a rewrite" in page
    code, _ = review(mono, tmp_path, gitleaks, published=unrelated, allow_rewrite=True)
    assert code == 0
    project = load_manifest(mono.path / "partlet.toml").projects["foo"]
    assert project.allow_rewrite_of == unrelated
    assert project.approved == export_tip(mono, tmp_path)


def test_allow_rewrite_without_a_rewrite_is_refused(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    with pytest.raises(ReviewError, match="nothing is published"):
        review(mono, tmp_path, gitleaks, allow_rewrite=True)


def test_fetch_published_tip(tmp_path, serve):
    (tmp_path / "foo" / "info").mkdir(parents=True)
    (tmp_path / "foo" / "info" / "refs").write_text(f"{'c' * 40}\trefs/heads/main\n")
    with serve(tmp_path) as base:
        assert fetch_published_tip(base, "foo") == "c" * 40
        assert fetch_published_tip(base, "bar") is None


def test_cli_review_then_build_publishes(mono, tmp_path, monkeypatch, capsys):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    args = ["review", "foo", "--repo", str(mono.path), "--published-tip", "none"]
    assert main(args) == 0
    assert "Approve" not in capsys.readouterr().out  # the prompt goes to input()
    git_out("commit", "-qam", "approve foo", cwd=mono.path)
    out = tmp_path / "out"
    assert main(["build", "--scan", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert "published" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_review.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'partlet.review'`.

- [ ] **Step 3: Implement the review**

`src/partlet/review.py`:

```python
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
    load_manifest,
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
    return [f for f in raw.decode("utf-8", "replace").split("\0") if f]


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
    objects = git("rev-list", "--objects", "refs/heads/main", cwd=repo).stdout
    checked = git(
        "cat-file",
        "--batch-check=%(objecttype) %(objectsize) %(rest)",
        cwd=repo,
        input=objects,
    ).stdout.decode("utf-8", "replace")
    sizes: dict[str, int] = {}
    for line in checked.splitlines():
        kind, size, path = line.split(" ", 2)
        if kind == "blob" and int(size) > cap:
            sizes[path] = max(sizes.get(path, 0), int(size))
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
    url = f"{base_url}/{name}/info/refs"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise ReviewError(f"cannot read {url}: HTTP {e.code}") from e
    except OSError as e:
        raise ReviewError(
            f"cannot read {url}: {e}; pass --published-tip SHA, or "
            "--published-tip none if nothing is published"
        ) from e
    for line in body.splitlines():
        sha, _, ref = line.partition("\t")
        if ref == "refs/heads/main" and SHA_RE.fullmatch(sha):
            return sha
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
    manifest = load_manifest(manifest_path)
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
    set_project_fields(manifest_path, name, fields)
    print(f"partlet: approved {report.tip[:12]} in {manifest_path}; commit and push it")
    return 0
```

- [ ] **Step 4: Add the command**

In `src/partlet/cli.py`:

1. Add `import pydoc` to the imports, `SHA_RE` to the `partlet.manifest` import, and:

```python
from partlet.export import ExportError
from partlet.gitutil import GitError
from partlet.review import ReviewError, fetch_published_tip, run_review
```

2. In `_parser`, before the `unlock` parser, add:

```python
    review = sub.add_parser(
        "review", help="report on a project's export and approve its tip"
    )
    review.add_argument("name", help="project name")
    _repo_args(review)
    review.add_argument(
        "--allow-rewrite",
        action="store_true",
        help="also allow the next publish to replace the published history",
    )
    review.add_argument(
        "--published-tip",
        metavar="SHA|none",
        help="the published tip, instead of reading <base_url>/<name>/info/refs",
    )
```

3. Add before `_exit_on_sigterm`:

```python
def _review(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    manifest_path = _manifest_path(args)
    try:
        manifest = load_manifest(manifest_path)
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
            )
    except (ManifestError, ToolError, ReviewError, ExportError, GitError) as e:
        return _error(e)
```

4. Add `"review": _review,` to `COMMANDS`.

`review` takes no lock: it writes only the local `partlet.toml`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_review.py -v`
Expected: all PASS.

Run: `bash scripts/check.sh`
Expected: `check: all gates passed`.

- [ ] **Step 6: Commit**

```bash
git add src/partlet/review.py src/partlet/cli.py tests/test_review.py
git commit -m "Add partlet review"
```

---

### Task 12: The composite action

Queue area `[ACTION]`. The CI job in Step 5 changes `.github/workflows/ci.yml`; ask the user before committing it.

**Files:**
- Create: `action.yml`, `action/requirements.txt`
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`
- Test: `tests/test_action.py`

**Interfaces:**
- Consumes: `partlet.cli` (`publish`, `build --scan`), `scripts/install-gitleaks.sh`.
- Produces: `uses: <owner>/partlet@<ref>` with inputs `account-id`, `access-key-id`, `secret-access-key`, `bucket`, `endpoint`, `repo` (default `.`), `manifest` (default `partlet.toml`), `local-out` (testing only).

How the action installs pinned tools:

- Python 3.12 comes from `astral-sh/setup-uv`, pinned to the commit of v10.3.0.
- Every Python dependency, git-filter-repo included, is installed with `uv pip install --require-hashes -r action/requirements.txt`, a lock generated from `pyproject.toml` with `uv pip compile --universal --generate-hashes`. A changed or substituted package fails the install.
- Partlet itself is not built or installed. It runs from the action's own checkout through `PYTHONPATH=<action>/src`, so the action ref pins its version (spec, "The monorepo"), and no build backend is downloaded unpinned at run time. `python -P` keeps the monorepo checkout (the working directory) off `sys.path`, so a file in the monorepo cannot shadow a module.
- gitleaks comes from `scripts/install-gitleaks.sh`, which checks the download against the SHA-256 recorded in the script.
- `partlet publish` then refuses to run unless filter-repo and gitleaks are exactly the pinned versions, and writes every tool version, git's included, into the step summary.

Git itself comes from the runner image and cannot be pinned the same way. The monorepo workflow pins the image (`runs-on: ubuntu-24.04`), and the summary records the git version for comparison (open question 2).

- [ ] **Step 1: Add the test dependency and generate the lock**

In `pyproject.toml`, add `"pyyaml>=6"` to the dev extra:

```toml
dev = ["moto[server]>=5.1", "pytest>=8", "pyyaml>=6", "ruff>=0.6"]
```

Run: `bash scripts/setup.sh && mkdir -p action && uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.12 --quiet -o action/requirements.txt`
Expected: `action/requirements.txt` pins, each with `--hash=sha256:` lines, `boto3`, `botocore`, `git-filter-repo==2.47.0`, `jinja2`, `jmespath`, `markdown-it-py`, `markupsafe`, `mdurl`, `pygments`, `python-dateutil`, `s3transfer`, `six`, `tomlkit` and `urllib3`. Regenerate it with the same command whenever `dependencies` in `pyproject.toml` change; the test below fails when a dependency is missing from it.

- [ ] **Step 2: Write the failing tests**

`tests/test_action.py`:

```python
"""Static checks on action.yml and the dependency lock it installs from."""

import re
import tomllib
from pathlib import Path

import yaml

from partlet.tools import FILTER_REPO_VERSION

ROOT = Path(__file__).resolve().parent.parent
ACTION = yaml.safe_load((ROOT / "action.yml").read_text())
STEPS = ACTION["runs"]["steps"]
SECRET_INPUTS = {"account-id", "access-key-id", "secret-access-key", "bucket"}


def test_composite_steps_run_in_bash():
    assert ACTION["runs"]["using"] == "composite"
    for step in STEPS:
        if "run" in step:
            assert step["shell"] == "bash"
            assert step["run"].lstrip().startswith("set -euo pipefail")


def test_third_party_actions_are_pinned_to_commits():
    for step in STEPS:
        if "uses" in step:
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", step["uses"]), step


def test_inputs_never_expand_inside_scripts():
    # Expressions in `run:` are pasted into the script before bash parses it,
    # so every input goes through `env:` instead.
    for step in STEPS:
        assert "${{" not in step.get("run", "")


def test_credentials_reach_only_the_publish_step():
    for step in STEPS:
        env = " ".join(str(v) for v in step.get("env", {}).values())
        used = {name for name in SECRET_INPUTS if f"inputs.{name} " in env + " "}
        if step.get("name") == "Publish":
            assert used == SECRET_INPUTS
        else:
            assert used == set(), step.get("name")


def test_python_never_imports_from_the_checkout():
    publish = next(s for s in STEPS if s.get("name") == "Publish")
    assert publish["run"].count('"$PY" -P -m partlet.cli') == 2


def test_requirements_are_hash_locked_and_cover_the_dependencies():
    lock = (ROOT / "action" / "requirements.txt").read_text()
    pinned = dict(re.findall(r"^([a-z0-9][a-z0-9._-]*)==(\S+) \\$", lock, re.MULTILINE))
    assert pinned["git-filter-repo"] == FILTER_REPO_VERSION
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    for dep in deps:
        name = re.split(r"[<>=!~\[ ]", dep, maxsplit=1)[0].lower()
        assert name in pinned, f"{name} missing from action/requirements.txt"
    for block in re.split(r"\n(?=[a-z])", lock.split("\n", 2)[2]):
        assert "--hash=sha256:" in block, block
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_action.py -v`
Expected: FAIL with `FileNotFoundError` for `action.yml`.

- [ ] **Step 4: Write the action**

`action.yml`:

```yaml
name: Partlet publish
description: Publish the approved projects in a monorepo's partlet.toml to a Partlet site in Cloudflare R2.
inputs:
  account-id:
    description: Cloudflare account ID. Pass it from a secret.
    required: false
  access-key-id:
    description: R2 access key ID, scoped to write the one bucket. Pass it from a secret.
    required: false
  secret-access-key:
    description: R2 secret access key. Pass it from a secret.
    required: false
  bucket:
    description: R2 bucket name. Pass it from a secret.
    required: false
  endpoint:
    description: R2 S3 endpoint, for a bucket in a jurisdiction (https://<account>.eu.r2.cloudflarestorage.com). Default is derived from account-id.
    required: false
    default: ""
  repo:
    description: Path of the monorepo checkout.
    required: false
    default: "."
  manifest:
    description: Manifest path, relative to repo.
    required: false
    default: partlet.toml
  local-out:
    description: For testing this action. Build into this directory instead of publishing to R2; needs no credentials.
    required: false
    default: ""
runs:
  using: composite
  steps:
    - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0

    - id: install
      name: Install Partlet and its pinned tools
      shell: bash
      env:
        ACTION_PATH: ${{ github.action_path }}
      run: |
        set -euo pipefail
        venv="$RUNNER_TEMP/partlet-venv"
        uv venv --quiet --python 3.12 "$venv"
        # Every dependency, git-filter-repo included, at the version and hash
        # in action/requirements.txt.
        uv pip install --quiet --python "$venv/bin/python" --require-hashes \
          -r "$ACTION_PATH/action/requirements.txt"
        bash "$ACTION_PATH/scripts/install-gitleaks.sh" "$venv/bin"
        echo "python=$venv/bin/python" >> "$GITHUB_OUTPUT"

    - name: Make sure the publishing branch exists locally
      shell: bash
      working-directory: ${{ inputs.repo }}
      env:
        PY: ${{ steps.install.outputs.python }}
        MANIFEST: ${{ inputs.manifest }}
      run: |
        set -euo pipefail
        branch=$("$PY" -I -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb")).get("site", {}).get("branch", "main"))' "$MANIFEST")
        if ! git rev-parse --verify --quiet "refs/heads/$branch^{commit}" >/dev/null; then
          if ! git rev-parse --verify --quiet "refs/remotes/origin/$branch^{commit}" >/dev/null; then
            echo "::error::Neither refs/heads/$branch nor origin/$branch exists; check out the monorepo with actions/checkout and fetch-depth: 0"
            exit 1
          fi
          git branch --no-track "$branch" "refs/remotes/origin/$branch"
        fi

    - name: Publish
      shell: bash
      working-directory: ${{ inputs.repo }}
      env:
        PY: ${{ steps.install.outputs.python }}
        # Partlet runs from the action's own checkout, so the action ref pins it.
        PYTHONPATH: ${{ github.action_path }}/src
        MANIFEST: ${{ inputs.manifest }}
        LOCAL_OUT: ${{ inputs.local-out }}
        PARTLET_R2_ACCOUNT_ID: ${{ inputs.account-id }}
        PARTLET_R2_ACCESS_KEY_ID: ${{ inputs.access-key-id }}
        PARTLET_R2_SECRET_ACCESS_KEY: ${{ inputs.secret-access-key }}
        PARTLET_R2_BUCKET: ${{ inputs.bucket }}
        PARTLET_R2_ENDPOINT: ${{ inputs.endpoint }}
      # -P: never put the monorepo checkout (the working directory) on
      # sys.path, so no file in it can shadow a module.
      run: |
        set -euo pipefail
        if [ -n "$LOCAL_OUT" ]; then
          exec "$PY" -P -m partlet.cli build --scan --repo . --manifest "$MANIFEST" --out "$LOCAL_OUT"
        fi
        exec "$PY" -P -m partlet.cli publish --repo . --manifest "$MANIFEST"
```

- [ ] **Step 5: Add the smoke job to CI (ask the user first)**

Add to `jobs:` in `.github/workflows/ci.yml`. It runs the action from this checkout against a synthetic monorepo whose checkout has no local `main`, the case the TODO entry calls out, in `local-out` mode, so it needs no credentials:

```yaml
  action:
    name: Action smoke test
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      # A monorepo checkout on a detached HEAD with no local main, as some
      # actions/checkout configurations leave it. The action must create
      # refs/heads/main from origin/main.
      - name: Make a monorepo checkout
        run: |
          set -euo pipefail
          git init -q -b main "$RUNNER_TEMP/origin"
          cd "$RUNNER_TEMP/origin"
          git config user.email ci@example.com
          git config user.name CI
          mkdir foo
          echo "# Foo" > foo/README.md
          printf '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n\n[projects.foo]\npath = "foo"\n' > partlet.toml
          git add -A
          git commit -qm init
          git clone -q "$RUNNER_TEMP/origin" "$RUNNER_TEMP/mono"
          cd "$RUNNER_TEMP/mono"
          git checkout -q --detach origin/main
          git branch -q -D main
      - uses: ./
        with:
          repo: ${{ runner.temp }}/mono
          local-out: ${{ runner.temp }}/site
      - name: Check the result
        run: |
          set -euo pipefail
          git -C "$RUNNER_TEMP/mono" rev-parse --verify refs/heads/main
          test "$(cat "$RUNNER_TEMP/site/s/index.json")" = "[]"
```

The unapproved project is skipped, but the run still covers the hash-locked install, the gitleaks install and version check (`build --scan` runs `check_tools`), branch creation and the build.

- [ ] **Step 6: Verify**

Run: `.venv/bin/pytest tests/test_action.py -v && bash scripts/check.sh`
Expected: all PASS; `check: all gates passed`.

To try the action's steps without GitHub, save each step's `run:` text to `step0.sh` to `step2.sh`, then, in a scratch monorepo clone with a detached HEAD and no local `main`, run them with `RUNNER_TEMP`, `GITHUB_OUTPUT` and the step's `env:` values exported. For a publish, point `PARTLET_R2_ENDPOINT` at a local moto server (`ThreadedMotoServer`). This was done while writing the plan. Both the `local-out` build and a publish of an approved project to moto succeeded, and the summary listed `partlet 0.1.0, git <version>, git-filter-repo 2.47.0, gitleaks 8.30.1`.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml action.yml action/requirements.txt tests/test_action.py .github/workflows/ci.yml
git commit -m "Add the composite action that publishes a monorepo"
```

Tagging a release (`v1`) is the user's (see "User-run steps").

---

### Task 13: End-to-end test through `wrangler dev`

Queue area `[TOOLING]`. Starts only after plan 2's Worker has landed. Step 4 changes `.github/workflows/ci.yml`; ask the user before committing it.

**Files:**
- Create: `tests/e2e/seed_local_r2.mjs`, `tests/e2e/test_wrangler.py`, `scripts/e2e.sh`
- Modify: `pyproject.toml`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: plan 2's `worker/` (interface under "Dependencies"), `publish_all`, `LocalStore`.
- Produces: `bash scripts/e2e.sh`; pytest marker `e2e`, deselected by default.

How it works: the publisher writes into a `LocalStore` directory, and `seed_local_r2.mjs` mirrors that directory into the local R2 bucket of the Worker's wrangler config. It uses wrangler's `getPlatformProxy` from `worker/node_modules`, so the storage format always matches the wrangler that serves it. Then `wrangler dev --local --persist-to <dir>` serves the Worker on a loopback port, and the test fetches pages and clones; it publishes again, re-seeds, serves again and pulls. Seeding and serving never overlap: wrangler's documentation does not say two processes may share the local storage at once. Nothing contacts Cloudflare. `--local` disables remote bindings, the sandbox has stripped every `CLOUDFLARE_*` variable, and `WRANGLER_SEND_METRICS=false`.

The harness was run while writing this plan against a minimal stand-in Worker that implemented only the routes the test uses. It passed in about 9 seconds. The real Worker replaces the stand-in.

- [ ] **Step 1: Register the marker**

In `pyproject.toml`, under `[tool.pytest.ini_options]`, add:

```toml
addopts = "-m 'not e2e'"
markers = ["e2e: end-to-end test through wrangler dev; run with scripts/e2e.sh"]
```

`scripts/test.sh` therefore deselects the test (not skips it), and `scripts/e2e.sh` selects it with `-m e2e`, which overrides `addopts`.

- [ ] **Step 2: Write the seeding script, the test and the runner**

`tests/e2e/seed_local_r2.mjs`:

```javascript
// Mirror a LocalStore directory into the local R2 bucket that
// `wrangler dev --local --persist-to <persist-dir>` serves.
//
// Usage: node seed_local_r2.mjs <worker-dir> <persist-dir> <store-dir>
//
// Uses wrangler's getPlatformProxy from the Worker's own node_modules, so
// the local storage format always matches the wrangler that serves it.
import { createRequire } from "node:module";
import { readdir, readFile } from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";

const [workerDir, persistDir, storeDir] = process.argv.slice(2).map((p) => resolve(p));
const require = createRequire(join(workerDir, "package.json"));
const { getPlatformProxy } = require("wrangler");

async function* files(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* files(path);
    else if (entry.isFile()) yield path;
  }
}

const { env, dispose } = await getPlatformProxy({
  configPath: join(workerDir, "wrangler.toml"),
  // `wrangler dev --persist-to X` keeps its data in X/v3; getPlatformProxy
  // uses the path as given.
  persist: { path: join(persistDir, "v3") },
  remoteBindings: false,
});
try {
  const wanted = new Set();
  for await (const path of files(storeDir)) {
    const key = relative(storeDir, path).split(sep).join("/");
    if (key.split("/").some((part) => part.startsWith(".partlet-tmp-"))) continue;
    wanted.add(key);
    await env.BUCKET.put(key, await readFile(path));
  }
  const stale = [];
  let cursor;
  do {
    const page = await env.BUCKET.list({ cursor });
    stale.push(...page.objects.map((o) => o.key).filter((k) => !wanted.has(k)));
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  for (const key of stale) await env.BUCKET.delete(key);
  console.log(`seeded ${wanted.size} keys, removed ${stale.length}`);
} finally {
  await dispose();
}
```

`tests/e2e/test_wrangler.py`:

```python
"""Publish, serve through the Worker under `wrangler dev`, clone, publish, pull.

Run with `bash scripts/e2e.sh`. Needs Node and `npm ci` in worker/. Never
talks to Cloudflare: wrangler runs with --local, without credentials (the
test sandbox strips them), against local R2 storage in a temporary directory.
"""

import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from helpers import export_tip

from partlet.export import export_project
from partlet.gitutil import git, git_out
from partlet.manifest import Project, parse_manifest
from partlet.publish import publish_all
from partlet.store import LocalStore

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "worker"
WRANGLER = WORKER / "node_modules" / ".bin" / "wrangler"
SEED = Path(__file__).with_name("seed_local_r2.mjs")
SOURCE = "s"


def node_env() -> dict[str, str]:
    return {**os.environ, "WRANGLER_SEND_METRICS": "false", "CI": "1"}


def seed(store_root: Path, persist: Path) -> None:
    subprocess.run(
        ["node", str(SEED), str(WORKER), str(persist), str(store_root)],
        check=True,
        env=node_env(),
        timeout=120,
    )


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


@contextmanager
def wrangler_dev(persist: Path, log: Path):
    """Serve the Worker on a free loopback port, from local R2 under `persist`.

    The two processes never share the storage at once: seed first, then
    serve, and stop serving before seeding again.
    """
    port = free_port()
    with log.open("ab") as out:
        proc = subprocess.Popen(
            [
                str(WRANGLER),
                "dev",
                "--local",
                "--persist-to",
                str(persist),
                "--ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--var",
                f"SOURCE:{SOURCE}",
                "--show-interactive-dev-session=false",
                "--log-level",
                "warn",
            ],
            cwd=WORKER,
            env=node_env(),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            assert proc.poll() is None, log.read_text()
            try:
                get(base + "/")
                break
            except OSError:
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(0.5)
        yield base
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def manifest(approved: str):
    return parse_manifest(f"""
[site]
source = "{SOURCE}"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
description = "Foo tool"
approved = "{approved}"
""")


def test_clone_and_pull_through_wrangler_dev(mono, tmp_path):
    assert WRANGLER.exists(), "run 'npm ci' in worker/ first"
    mono.write("foo/README.md", "# Foo\n")
    mono.write("foo/src/a.py", "print('a')\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store_root = tmp_path / "store"
    persist = tmp_path / "persist"
    log = tmp_path / "wrangler.log"

    (result,) = publish_all(
        mono.path, manifest(approved), LocalStore(store_root), tmp_path / "w1"
    )
    assert result.status == "published"
    seed(store_root, persist)
    clone = tmp_path / "clone"
    with wrangler_dev(persist, log) as base:
        status, page = get(f"{base}/foo")
        assert status == 200 and b"Foo" in page
        assert get(f"{base}/foo/raw/src/a.py") == (200, b"print('a')\n")
        assert b'href="/foo"' in get(f"{base}/")[1]
        status, refs = get(f"{base}/foo/info/refs?service=git-upload-pack")
        assert (status, refs) == (200, f"{approved}\trefs/heads/main\n".encode())
        assert get(f"{base}/foo/archive/foo.tar.gz")[0] == 200
        git("clone", "-q", f"{base}/foo", str(clone), cwd=tmp_path)
        git("clone", "-q", f"{base}/foo.git", str(tmp_path / "alias"), cwd=tmp_path)
    assert git_out("rev-parse", "HEAD", cwd=clone) == approved

    mono.write("foo/b.txt", "two\n")
    mono.commit("c2")
    (result,) = publish_all(
        mono.path, manifest(approved), LocalStore(store_root), tmp_path / "w2"
    )
    assert result.status == "published"
    seed(store_root, persist)
    with wrangler_dev(persist, log) as base:
        git("remote", "set-url", "origin", f"{base}/foo", cwd=clone)
        git("pull", "-q", "--ff-only", cwd=clone)
    new_tip = export_project(
        mono.path, "main", Project("foo", "foo"), tmp_path / "check.git"
    )
    assert git_out("rev-parse", "HEAD", cwd=clone) == new_tip
    assert git_out("ls-tree", "-r", "HEAD", cwd=clone) == git_out(
        "ls-tree", "-r", new_tip, cwd=tmp_path / "check.git"
    )
```

`scripts/e2e.sh` (mode 0755):

```bash
#!/usr/bin/env bash
# End-to-end test: publish into a local store, serve it through the Worker
# with `wrangler dev --local` and local R2, then clone and pull. Needs Node
# and the Worker's dependencies (npm ci in worker/). Never contacts
# Cloudflare. See docs/QUALITY.md.
set -euo pipefail
cd "$(dirname "$0")/.."

# Git hooks export GIT_DIR and friends; drop them so the tests cannot act on the enclosing repository.
for var in $(git rev-parse --local-env-vars); do unset "$var"; done

command -v node >/dev/null || { echo "e2e: node is required" >&2; exit 1; }
[ -x worker/node_modules/.bin/wrangler ] || { echo "e2e: run 'npm ci' in worker/ first" >&2; exit 1; }

# pytest exits 5 when it collects nothing, so a missing test fails this script.
.venv/bin/pytest -q -m e2e tests/e2e "$@"
```

- [ ] **Step 3: Run it**

Run: `npm ci --prefix worker && bash scripts/e2e.sh`
Expected: `1 passed`. If the Worker's routes or config names differ from the assumed interface, change `WORKER`/`SEED` constants or the `configPath` in the seeding script, not the assertions, and record the difference in the PR.

Run: `.venv/bin/pytest --collect-only -q | tail -1`
Expected: `... (1 deselected)`.

- [ ] **Step 4: Add the CI job (ask the user first)**

Add to `jobs:` in `.github/workflows/ci.yml`, matching the Node setup plan 2 uses for its Worker tests (wrangler 4.151.1 needs Node 22 or newer):

```yaml
  e2e:
    name: End-to-end (wrangler dev)
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: bash scripts/setup.sh
      - run: npm ci --prefix worker
      - run: bash scripts/e2e.sh
```

Drop the `npm ci` line if plan 2's `scripts/setup.sh` already installs the Worker's dependencies.

- [ ] **Step 5: Commit**

```bash
chmod +x scripts/e2e.sh
git add pyproject.toml tests/e2e scripts/e2e.sh .github/workflows/ci.yml
git commit -m "Add the end-to-end test through wrangler dev and its CI job"
```

---

### Task 14: Documentation

Queue area `[DOCS]`. Each group below goes in the PR named, because that PR makes the old text inaccurate.

- [ ] **PR 1 (Tasks 1 to 4)**

`docs/QUALITY.md`:
- Test policy: after the sandbox sentence, add that the sandbox also removes `AWS_*`, `R2_*`, `PARTLET_R2_*`, `CLOUDFLARE_*`, `CF_*`, `WRANGLER_*` and `GITLEAKS_*` variables, points the AWS SDK at missing config files, and lets sockets connect to loopback addresses only, so no test can reach a real bucket or any other outside service.
- Toolchain pins: add "git-filter-repo 2.47.0 exactly (`pyproject.toml`; export hashes depend on it); gitleaks 8.30.1 exactly, installed by `scripts/install-gitleaks.sh` with a SHA-256 per platform".

`docs/DECISIONS.md`, in the 2026-10-17 section:

| Decision | Reason and trade-off |
| --- | --- |
| CI scans each export's full history with gitleaks on every run that uploads, not only the commits since the published tip. | The spec scans `published..new` in CI and relies on `partlet review` for the rest, but CI cannot tell whether a review scan happened, or with which configuration. A full scan makes the approval pin unable to publish a secret anywhere in history. Cost: scan time grows with project history, and a rule or allowlist change can block a project that published before; accept the finding in `.gitleaks.toml` or `.gitleaksignore`. |
| gitleaks is pinned to one release by SHA-256 per platform in `scripts/install-gitleaks.sh`, run with `--exit-code 0 --redact`, and its findings are read from the JSON report. | gitleaks exits 1 both for findings and for errors, so the exit status cannot tell a finding from a broken scan. Redaction keeps secrets out of the report, results and step summary. Cost: a bump changes five lines and needs its own PR. |
| git-filter-repo is pinned with `==` in `pyproject.toml`, and publishing refuses any other installed version. | Export commit hashes depend on filter-repo's behaviour (see the 2026-10-15 entry on empty move commits). |

`docs/specs/2026-10-15-partlet-design.md`, "Secret scanning": replace the first bullet with "In CI, gitleaks scans the full history of each export before anything is uploaded; a finding fails that project and nothing of it is written." In "Repositories and components", give `scan.py` its real description ("gitleaks wrapper: full-history scan, pinned version check") and add `tools.py`.

- [ ] **PR 2 (Tasks 5 to 9)**

`docs/DECISIONS.md`:

| Decision | Reason and trade-off |
| --- | --- |
| Publishes to one source are serialised twice: the monorepo workflow's `concurrency` group, and a `<source>/lock` object created with a conditional put (`If-None-Match: *`) that every `build`, `publish` and `unpublish` holds for its whole run. A held lock fails the run, and only `partlet unlock` removes a stale one. | The sweep deletes every key no pointer names, so an overlapping run can delete objects another has uploaded but not yet pointed at, and later publishes do not repair that. The concurrency group covers the workflow's own runs only; the lock also covers local runs and other repositories or workflows publishing the same source. No automatic expiry: expiring the lock of a slow but live run would reopen the race. Cost: a run killed without warning blocks publishing until the user runs `partlet unlock`. |
| The R2 store uses boto3 against R2's S3-compatible API, with checksums only where an operation requires them, and treats only `NoSuchKey` as a missing key. | boto3 is the client the R2 documentation shows for Python. Pinning the checksum mode keeps behaviour independent of botocore's changing defaults. `NoSuchBucket` is also a 404, and reading it as "nothing published" would make a misconfigured bucket look like a first publication. |
| R2 credentials are read from `PARTLET_R2_*` once and removed from the process environment before any child process starts; the store refuses endpoints that are not `https`, except loopback for tests. | git, filter-repo and gitleaks never inherit the keys, and the keys cannot be sent in clear text or to a URL with embedded credentials. |
| `partlet publish` refuses to run unless HEAD is the tip of the local publishing branch and `partlet.toml` matches the committed version. | The export reads the branch while the approval pins come from the working tree; requiring them to agree stops pins that were never committed from being published, and stops publishes from pull request or feature-branch checkouts. |

`docs/specs/2026-10-15-partlet-design.md`:
- "R2 layout": add `<source>/lock` with "present only while a run holds it".
- "Error handling": after the `concurrency` bullet, add that every run also holds the store lock, and that `partlet unlock` removes one left by a run that died.
- "Other commands": add `partlet unlock`.
- "The monorepo", item 3: name the secrets `PARTLET_R2_ACCOUNT_ID`, `PARTLET_R2_ACCESS_KEY_ID`, `PARTLET_R2_SECRET_ACCESS_KEY`, `PARTLET_R2_BUCKET`.

`docs/QUALITY.md`, "Review inputs", baseline commands: add `partlet publish` against the moto fixture's endpoint as the way to exercise the R2 path locally.

- [ ] **PR 3 (Tasks 10 and 11)**

`docs/DECISIONS.md`:

| Decision | Reason and trade-off |
| --- | --- |
| `partlet review` reads the published tip from the public site (`<base_url>/<name>/info/refs`), not from R2. | Review then needs no R2 credentials on the user's machine. `--published-tip` covers a site that is unreachable or not yet deployed. |
| Review refuses to approve while gitleaks reports findings, or a non-fast-forward tip without `--allow-rewrite`. | CI would refuse either publish; refusing at review keeps a pin that cannot publish out of `partlet.toml`. |

- [ ] **PR 4 (Task 12)**

`README.md`: a "Publishing a monorepo" section with:
- what the monorepo carries (`partlet.toml`, the workflow below, four secrets) and a pointer to "User-run steps" in this plan for the one-time Cloudflare and GitHub setup;
- the workflow:

```yaml
name: Partlet
on:
  push:
    branches: [main]        # the publishing branch in partlet.toml
  workflow_dispatch:
permissions:
  contents: read
# Required. Publishes to one source must never overlap: each run deletes
# objects no pointer names, including ones another run has just uploaded.
concurrency:
  group: partlet-<source>   # the site.source value from partlet.toml
  cancel-in-progress: false
jobs:
  publish:
    runs-on: ubuntu-24.04   # pinned image: export hashes depend on tool versions
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          fetch-depth: 0              # publishing needs full history
          persist-credentials: false  # keep the GitHub token out of git config
      - uses: <owner>/partlet@v1
        with:
          account-id: ${{ secrets.PARTLET_R2_ACCOUNT_ID }}
          access-key-id: ${{ secrets.PARTLET_R2_ACCESS_KEY_ID }}
          secret-access-key: ${{ secrets.PARTLET_R2_SECRET_ACCESS_KEY }}
          bucket: ${{ secrets.PARTLET_R2_BUCKET }}
```

- reviewing a project locally: clone Partlet, `bash scripts/setup.sh` (installs the pinned gitleaks into `.venv/bin`), then `.venv/bin/partlet review <name> --repo <monorepo>`; commit and push the pin;
- unpublishing: remove the project from `partlet.toml` and push, then, with the four `PARTLET_R2_*` variables set and no publish running, `partlet unpublish <name> --repo <monorepo>`;
- a stale lock: `partlet unlock --repo <monorepo>`, after checking the run it names has ended.

`docs/QUALITY.md`: "CI" gains the `Action smoke test` job; "Expected tracked files" gains `action.yml` and `action/requirements.txt`; toolchain pins gain "action dependencies: `action/requirements.txt`, hash-locked, regenerated with `uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.12 -o action/requirements.txt`".

`docs/DECISIONS.md`:

| Decision | Reason and trade-off |
| --- | --- |
| The action installs every Python dependency from a hash-locked `action/requirements.txt` and runs Partlet from its own checkout with `python -P` and `PYTHONPATH`, instead of building and installing the package. | The job holds R2 write credentials, so nothing it runs is resolved at run time: no unpinned build backend, no newer transitive dependency, nothing imported from the monorepo checkout. Cost: the lock is regenerated whenever `dependencies` change (a test catches a missing package). |

`docs/specs/2026-10-15-partlet-design.md`, "The monorepo": the workflow uses `persist-credentials: false`, `runs-on: ubuntu-24.04`, and a concurrency group per source; and the action creates `refs/heads/<branch>` from `origin/<branch>` if the checkout lacks it.

- [ ] **PR 5 (Task 13)**

`docs/QUALITY.md`: add `scripts/e2e.sh` to the gates table (CI on PR and main, through the `e2e` job; not in `check.sh`, because it needs Node and the Worker's dependencies), and the `e2e` job to "CI". `.mjs` joins the expected tracked files.

---

## User-run steps

Agents do not run anything in this section. Cloudflare R2 and Workers are billable, and tokens, secrets, settings and tags are the user's. Each step is written for the user to run when the matching PR has landed.

**U1. USER STEP: create the bucket (billable).** In the Cloudflare dashboard under R2, or with `npx wrangler r2 bucket create <bucket>` from `worker/` (needs `wrangler login`). Use the same bucket name in the Worker's `wrangler.toml` (plan 2) and in the monorepo secret below.

**U2. USER STEP: create a token scoped to that bucket.** R2 > Overview > Account Details > API Tokens > Manage > Create Account API token. Permissions: **Object Read & Write**, limited to the one bucket. Copy the Access Key ID and Secret Access Key when shown; the secret cannot be retrieved later. The Worker never gets this token. It reads through its bucket binding.

**U3. USER STEP: deploy the Worker (billable).** As plan 2 describes (`wrangler deploy` from `worker/`).

**U4. USER STEP: add the monorepo secrets.**

```bash
gh secret set PARTLET_R2_ACCOUNT_ID --repo <owner>/<monorepo>
gh secret set PARTLET_R2_ACCESS_KEY_ID --repo <owner>/<monorepo>
gh secret set PARTLET_R2_SECRET_ACCESS_KEY --repo <owner>/<monorepo>
gh secret set PARTLET_R2_BUCKET --repo <owner>/<monorepo>
```

`gh secret set` prompts for each value, so the values stay out of shell history.

**U5. USER STEP: allow the monorepo to use the action**, if this repository is private: Settings > Actions > General > Access, "Accessible from repositories owned by the user".

**U6. USER STEP: release the action** after PR 4 lands:

```bash
git tag -a v1.0.0 -m "Partlet action v1.0.0"
git push origin v1.0.0
git tag -f v1 v1.0.0
git push --force origin v1
```

Moving `v1` later is a force-push of a tag; it is the user's each time.

**U7. USER STEP: first publication.** In the monorepo, add `partlet.toml` and `.github/workflows/partlet.yml` (README, PR 4), run `partlet review <name>` for each project, commit the pins, and push. Check the step summary of the first run.

## Open questions for the user

1. **Full-history scan in CI.** This plan scans each export's full history on every uploading run, as the brief for this plan asked; the spec scans only new commits in CI. The spec is updated in PR 1 if you agree.
2. **Git version.** The spec says the action pins git. Hosted runners do not allow that; the plan pins the runner image in the workflow template and records git's version in the summary. Is that enough, or should `partlet publish` refuse an unexpected git version too?
3. **Cache lifetime and the sweep's grace.** The sweep keeps superseded objects for one publish; clients may cache `objects/info/packs` for 60 seconds. Two publishes less than a minute apart can break a fetch in progress (Review Focus 6). Leave it, or file a TODO for a minimum age before the sweep deletes a superseded key?
4. **The lock fails closed.** A run killed without warning blocks publishing until `partlet unlock`. The alternative, expiring locks after a time, reopens the race for slow runs. Confirm failing closed.
5. **Unpublish from CI.** `unpublish` runs on the user's machine with the R2 keys. Should the action also offer a `workflow_dispatch`-driven unpublish, which would keep the keys off your machine and inside the concurrency group?
6. **Suite time.** With this plan the default suite takes about 2 minutes 45 seconds on a laptop (58 seconds on `main` at 688469a, before the orphan sweep's tests), mostly gitleaks runs, moto round trips and Task 7's exhaustive test (about 40 seconds). Pre-push runs it. Acceptable, or should Task 7 move to a CI-only marker?
