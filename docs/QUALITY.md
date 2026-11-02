# Quality and validation

Read when changing code or preparing a PR. This document describes the gates as they exist now; history and rationale for past changes live in `docs/DECISIONS.md` and git.

## What quality means here

- Published history is stable: the same monorepo history and manifest always export to the same commit hashes, and nothing already published is rewritten without explicit approval.
- Privacy: nothing outside a project's declared paths reaches the public store, and the public Worker never holds credentials for the private repository.
- A plain `git clone` and `git pull` work against the published site with no client configuration.
- Rendered pages never execute content from the published repository (no scripts, escaped Markdown HTML, raw files served with safe content types).
- Deliberately manual for now: page appearance, and the user's historical review of a project before its first publication.

## Gates

Each check is a standalone script in `scripts/` or `docket/scripts/`, runnable from any directory, exiting non-zero on failure. Hooks, CI and agents run the same scripts.

| Script | Runs | Pre-commit | Pre-push | CI on PR | CI on main | Scheduled |
| --- | --- | --- | --- | --- | --- | --- |
| `scripts/fmt-check.sh` | `ruff format --check` over `src` and `tests` | yes | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/lint.sh` | shellcheck over `scripts/*.sh` and `.githooks/*`, then `ruff check` over `src` and `tests` | yes | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/test.sh` | pytest; fails on an empty collection | | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/worker-lint.sh` | Biome format/lint and smoke-driver Ruff | yes | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/worker-typecheck.sh` | generated Wrangler types, source and test TypeScript | | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/worker-test.sh` | Vitest in workerd with simulated R2; empty suite fails | | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/worker-bundle.sh` | Wrangler deploy bundle dry-run; no deployment | | via `check.sh` | via `check.sh` | via `check.sh` | |
| `scripts/worker-smoke.sh` | actual publisher, local R2 and Wrangler clone/pull | | via `check.sh` | via `check.sh` | via `check.sh` | |
| `docket/scripts/ci.sh` | queue hygiene, Markdown links, PR markers against the queues | | | yes | yes | |
| `docket/scripts/check-queues.sh --strict` | queue hygiene | yes | | via `ci.sh` | via `ci.sh` | |
| `docket/scripts/check-links.sh` | relative Markdown links resolve | yes | | via `ci.sh` | via `ci.sh` | |
| `scripts/check.sh` | all gates in its `gates` array, cheapest first | | yes | yes | yes | |

`scripts/check.sh` is the composite entry point: `ci.yml` runs it rather
than the gates individually. Worker runtime tests and the smoke check
use local simulated bindings only; no cloud account is required.

Hooks are a tracked `.githooks/` directory, wired with `git config core.hooksPath .githooks` by `bash scripts/setup.sh`. Pre-commit runs the format check, lint and the queue and link validators on the whole working tree; it only checks and never rewrites files. Pre-push runs `bash scripts/check.sh`, including the test suite. Bypassing a hook is for a broken toolchain only; state the bypass and the equivalent checks in the PR.

Toolchain pins: Python 3.12 (`scripts/setup.sh`); git 2.31 or newer
(`rev-parse --path-format` and first-parent merge diffs); git-filter-repo
2.47.0 exactly (`pyproject.toml`; export hashes depend on it); gitleaks
8.30.1 exactly, installed by `scripts/install-gitleaks.sh` with a SHA-256
per platform. Other Python dependencies have floors in `pyproject.toml`.
The tool checks record the actual Git version; they do not establish
identical export hashes across different Git versions. Worker pins: Node
in `worker/.node-version`; exact npm dependencies and install-script
allowlist in `worker/package.json`, resolved by its committed lockfile;
Workers compatibility date in `worker/wrangler.toml`. Setup requires
npm >=11.19 to enforce the allowlist and uses `npm ci`. Bumping a pin is
its own PR. See the [Worker guide](../worker/README.md) for individual
gates, local preview and the cache/retention evidence limit.

## Test policy

- Behaviour changes come with a test at the lowest layer that can show the behaviour; Git behaviour (exports, history checks, clone and pull) is tested against real repositories built in the test, not mocks.
- Documentation-only changes need no new tests; `docket/scripts/check-links.sh` covers their links.
- An empty or skipped suite is a failed gate.
- Tests run git in a sandbox: `tests/conftest.py` removes inherited `GIT_*` variables when it is imported. At session start, before test modules are collected, it arms the tripwire, points `HOME` and the global git config at a temporary directory, moves the process into a directory under pytest's base temp, and sets `GIT_CEILING_DIRECTORIES` so implicit repository discovery cannot leave the temporary area. The tripwire fails the run, with a diff and a backup to compare against, if this repository's git config, `HEAD`, branch refs (including the main checkout's `HEAD` and `main`), the worktree's `.git` file, or the user's global git config change during the run. Configuration cleanup restores the original environment and working directory, including after collect-only runs and collection errors. `scripts/test.sh` also unsets git's repository variables before starting pytest.
- Before collection, the sandbox also removes `AWS_*`, `R2_*`,
  `PARTLET_R2_*`, `CLOUDFLARE_*`, `CF_*`, `WRANGLER_*` and `GITLEAKS_*`
  variables, points the AWS SDK at missing config files, disables its
  instance metadata lookup, and lets Python sockets connect to loopback
  addresses only. DNS lookups, UDP and subprocess sockets are not blocked;
  child processes inherit the stripped environment and tests point them
  only at local paths or simulated loopback services. The sandbox also
  unsets `GITHUB_STEP_SUMMARY`, `GITHUB_OUTPUT`, `GITHUB_ENV` and
  `GITHUB_PATH`. Environment, sockets and working directory are restored
  when pytest exits, including after collection errors.
- No automatic retries. A flaky test is filed in `TODO.md` with its evidence and fixed or quarantined by name.

## Review inputs

Read by `docket/CODE_REVIEW_GUIDE.md`, which links this section by its heading, so keep the heading as it is; a codebase review runs and records exactly what is listed here.

- Focus areas: the properties under [What quality means here](#what-quality-means-here) and the design in `docs/specs/`.
- Baseline commands beyond `bash scripts/check.sh`: `partlet build --out <dir>` against a synthetic monorepo, then `git clone` from that directory served over HTTP.
- Drift checks for an incremental review: this document against `.githooks/`, `scripts/` and `.github/workflows/`; plan status in `plans/` against merged work.
- Source paths for `bash docket/scripts/review-due.sh --paths "src worker scripts"`.
- Expected tracked files: Markdown, shell scripts, YAML under `.github/`, `.githooks/*`, `LICENSE`, `.gitignore`; Python, TOML, TypeScript, JSON, HTML and CSS once the publisher and Worker land.

## CI

`.github/workflows/ci.yml` runs on pull requests and on pushes to `main`. Jobs: `check` (runs `bash scripts/setup.sh` then `bash scripts/check.sh`) and `Queue and PR hygiene` (runs `bash docket/scripts/ci.sh`; on pull requests its marker check compares the queues at the base branch tip with the checked-out merge commit). Superseded runs are cancelled on PR branches only, never on `main`.

## Scheduled validation of main

Deferred until there is code worth an extended run; see the Docket section of `AGENTS.md`.

## Branch protection

Not configured yet. The settings are recorded here once the user applies them.

## PR evidence

Every PR lists the commands run and their results, a reproducible scenario for behaviour changes, what was not run and why, and the independent review. See [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).
