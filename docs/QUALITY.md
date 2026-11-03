# Quality and validation

Read when changing code or preparing a PR. This document describes the
gates as they exist now; history and rationale for past changes live in
`docs/DECISIONS.md` and git.

## What quality means here

- Published history is stable: the same monorepo history and manifest
  always export to the same commit hashes, and nothing already published
  is rewritten without explicit approval.
- Privacy: nothing outside a project's declared paths reaches the public
  store, and the public Worker never holds credentials for the private
  repository.
- A plain `git clone` and `git pull` work against the published site
  with no client configuration.
- Rendered pages never execute content from the published repository (no
  scripts, escaped Markdown HTML, raw files served with safe content
  types).
- Deliberately manual for now: page appearance, and the user's
  historical review of a project before its first publication.

## Gates

Each check is a standalone script in `scripts/` or `docket/scripts/`,
runnable from any directory, exiting non-zero on failure. Hooks, CI and
agents run the same scripts.

| Script | Runs | Pre-commit | Pre-push | CI on PR | CI on main | Scheduled |
| -- | -- | -- | -- | -- | -- | -- |
| `scripts/fmt-check.sh` | Ruff over `src`, `tests` and `action`; mdformat over tracked Markdown outside `docket/` | yes | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/lint.sh` | shellcheck over `scripts/*.sh`, `action/*.sh` and `.githooks/*`, then `ruff check` over `src`, `tests` and `action` | yes | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/test.sh` | pytest; fails on an empty collection |  | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/worker-lint.sh` | Biome format/lint and smoke-driver Ruff | yes | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/worker-typecheck.sh` | generated Wrangler types, source and test TypeScript |  | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/worker-test.sh` | Vitest in workerd with simulated R2; empty suite fails |  | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/worker-bundle.sh` | Wrangler deploy bundle dry-run; no deployment |  | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/worker-smoke.sh` | actual publisher, local R2 and Wrangler clone/pull |  | via `check.sh` | via `check.sh` | via `check.sh` |  |
| `scripts/e2e.sh` | actual review/publish/unpublish CLI, simulated S3, local R2 and public Worker routes |  |  | via `e2e` job | via `e2e` job |  |
| `docket/scripts/ci.sh` | queue hygiene, Markdown links, PR markers against the queues |  |  | yes | yes |  |
| `docket/scripts/check-queues.sh --strict` | queue hygiene | yes |  | via `ci.sh` | via `ci.sh` |  |
| `docket/scripts/check-links.sh` | relative Markdown links resolve | yes |  | via `ci.sh` | via `ci.sh` |  |
| `scripts/check.sh` | all gates in its `gates` array, cheapest first |  | yes | yes | yes |  |

`scripts/check.sh` is the composite entry point: `ci.yml` runs it rather
than the gates individually. Worker runtime tests and the smoke check
use local simulated bindings only; no cloud account is required.

Hooks are a tracked `.githooks/` directory, wired with
`git config core.hooksPath .githooks` by `bash scripts/setup.sh`.
Pre-commit first formats staged Markdown with
`bash scripts/fmt-markdown.sh --staged`. If it rewrites a file, the
commit stops so you can review and stage the result; it never changes
the index. Partially staged Markdown is checked from the index, and an
unformatted staged version stops the commit without touching the working
copy. Then pre-commit runs the format check, lint and the queue and link
validators on the whole working tree. Pre-push runs
`bash scripts/check.sh`, including the test suite. Bypassing a hook is
for a broken toolchain only; state the bypass and equivalent checks in
the PR.

Run `bash scripts/fmt-markdown.sh` to format all tracked Markdown, or
add `--check` for a read-only check. The pinned mdformat and GitHub
Flavored Markdown plugin are installed with the development
dependencies. The root `.mdformat.toml` sets 72-column wrapping and GFM
support, including tables and task lists. File selection includes `.md`
and `.markdown` extensions, case-insensitively; untracked files, deleted
files, symlinks and vendored `docket/` files are excluded from
whole-tree formatting.

`AGENTS.md`, `TODO.md` and `review/BACKLOG.md` use unwrapped prose so
Docket's line-based settings and queue parsers retain complete fields.
This override applies to manual formatting, checks and staged content.

Toolchain pins: Python 3.12 (`scripts/setup.sh`); git 2.31 or newer
(`rev-parse --path-format` and first-parent merge diffs);
git-filter-repo 2.47.0 exactly (`pyproject.toml`; export hashes depend
on it); gitleaks 8.30.1 exactly, installed by
`scripts/install-gitleaks.sh` with a SHA-256 per platform. Setup runs
the installer, so the CI `check` job downloads the pinned scanner. Other
Python dependencies have floors in `pyproject.toml`. The Action installs
hash-locked wheels from `action/requirements.txt` and uses the code in
its own selected checkout. Its uv download is pinned to 0.13.5 with
per-architecture checksums and Actions caching disabled. Regenerate the
lock using the command in the
[README](../README.md#development-and-validation). The tool checks
record the actual Git version; they do not establish identical export
hashes across different Git versions. Worker pins: Node in
`worker/.node-version`; exact npm dependencies and install-script
allowlist in `worker/package.json`, resolved by its committed lockfile;
Workers compatibility date in `worker/wrangler.toml`. Setup requires npm
\>=11.19 to enforce the allowlist and uses `npm ci`. Bumping a pin is its
own PR. See the [Worker guide](../worker/README.md) for individual
gates, local preview and the cache/retention evidence limit.

## Test policy

- Behaviour changes come with a test at the lowest layer that can show
  the behaviour; Git behaviour (exports, history checks, clone and pull)
  is tested against real repositories built in the test, not mocks.
- Documentation-only changes need no new tests;
  `docket/scripts/check-links.sh` covers their links.
- An empty or skipped suite is a failed gate.
- Tests run git in a sandbox: `tests/conftest.py` removes inherited
  `GIT_*` variables when it is imported. At session start, before test
  modules are collected, it arms the tripwire, points `HOME` and the
  global git config at a temporary directory, moves the process into a
  directory under pytest's base temp, and sets `GIT_CEILING_DIRECTORIES`
  so implicit repository discovery cannot leave the temporary area. The
  tripwire fails the run, with a diff and a backup to compare against,
  if this repository's git config, `HEAD`, branch refs (including the
  main checkout's `HEAD` and `main`), the worktree's `.git` file, or the
  user's global git config change during the run. Configuration cleanup
  restores the original environment and working directory, including
  after collect-only runs and collection errors. `scripts/test.sh` also
  unsets git's repository variables before starting pytest.
- Before collection, the sandbox also removes `AWS_*`, `R2_*`,
  `PARTLET_R2_*`, `CLOUDFLARE_*`, `CF_*`, `WRANGLER_*` and `GITLEAKS_*`
  variables, points the AWS SDK at missing config files, disables its
  instance metadata lookup, and lets Python sockets connect to loopback
  addresses only. DNS lookups, UDP and subprocess sockets are not
  blocked; child processes inherit the stripped environment and tests
  point them only at local paths or simulated loopback services. The
  sandbox also unsets `GITHUB_STEP_SUMMARY`, `GITHUB_OUTPUT`,
  `GITHUB_ENV` and `GITHUB_PATH`. Environment, sockets and working
  directory are restored when pytest exits, including after collection
  errors.
- No automatic retries. A flaky test is filed in `TODO.md` with its
  evidence and fixed or quarantined by name.

## Review inputs

Read by `docket/CODE_REVIEW_GUIDE.md`, which links this section by its
heading, so keep the heading as it is; a codebase review runs and
records exactly what is listed here.

- Focus areas: the properties under
  [What quality means here](#what-quality-means-here) and the design in
  `docs/specs/`.
- Baseline commands beyond `bash scripts/check.sh`:
  `partlet build --out <dir>` against a synthetic monorepo, then
  `git clone` from that directory served over HTTP. Exercise
  `partlet publish` against the moto fixture's loopback endpoint for the
  R2 path; the normal suite includes full interruption/retry checks.
- Drift checks for an incremental review: this document against
  `.githooks/`, `scripts/` and `.github/workflows/`; plan status in
  `plans/` against merged work.
- Source paths for
  `bash docket/scripts/review-due.sh --paths "src worker scripts"`.
- Expected tracked files: Markdown, shell scripts, YAML under
  `.github/`, `.githooks/*`, `LICENSE`, `.gitignore`; Python, TOML,
  TypeScript, JSON, HTML and CSS, plus `action.yml`,
  `action/requirements.txt` and the consumer example in `examples/`.

## CI

`.github/workflows/ci.yml` runs on pull requests and on pushes to
`main`. Jobs: `check` (runs `bash scripts/setup.sh` then
`bash scripts/check.sh`) and `Queue and PR hygiene` (runs
`bash docket/scripts/ci.sh`; on pull requests its marker check compares
the queues at the base branch tip with the checked-out merge commit).
Superseded runs are cancelled on PR branches only, never on `main`.

The `Action smoke test` job runs the composite Action itself against an
approved synthetic source on a detached checkout with no local
publishing branch. It installs locked wheels and checksum-verified
tools, creates the missing branch and publishes to a local store.
Private shadow modules fail if imported. Default Python tests also run
the actual prepare and publish shell steps, including the R2 backend
against loopback S3, committed approval, shallow/incorrect branches and
consumer concurrency. No cloud secrets or deployed Worker are used.

The `Publisher-to-Worker end-to-end` job runs `bash scripts/e2e.sh` with
the pinned Worker toolchain. Its pytest marker is excluded from the
default Python suite and selected explicitly by the runner; no tests are
skipped to pass the feature gate. The scenario covers actual CLI review,
committed approval, R2 publication against local S3, exact mirroring
into local R2, public clone/pull, pages/raw/archives, unchanged
publication, secret rejection and CLI removal. Rapid consolidation keeps
an old snapshot fetchable while a compliant metadata cache also clones
the new tip. Clock-controlled tests verify the one-hour retirement
expiry, interrupted writes, revival and orphan cleanup. See the
[retention contract](PUBLISHING.md#serialization-and-recovery).

Local S3 and the Worker binding are joined by a test mirror; these
checks do not establish hosted R2 API/binding coherence. Public URLs
always go through the Worker. Typescript runtime checks verify content
headers and bytes; actual browser execution and real private data are
user-run proof. JavaScript modules (`.mjs`) are tracked for local R2
tooling.

## Scheduled validation of main

Deferred until there is code worth an extended run; see the Docket
section of `AGENTS.md`.

## Branch protection

The `main` branch requires `check` and `Queue and PR hygiene`. Requiring
the branch to be up to date before merging is disabled. No approving
review count is required, and administrators are exempt. These settings
were verified on 2026-11-03; changes remain the user's decision.

## PR evidence

Every PR lists the commands run and their results, a reproducible
scenario for behaviour changes, what was not run and why, and the
independent review. See
[docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).
