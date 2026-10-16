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
| `scripts/lint.sh` | shellcheck over `scripts/*.sh` and `.githooks/*` | via `check.sh` | | via `check.sh` | via `check.sh` | |
| `docket/scripts/ci.sh` | queue hygiene, Markdown links, PR markers against the queues | | | yes | yes | |
| `docket/scripts/check-queues.sh --strict` | queue hygiene | yes | | via `ci.sh` | via `ci.sh` | |
| `docket/scripts/check-links.sh` | relative Markdown links resolve | yes | | via `ci.sh` | via `ci.sh` | |
| `scripts/check.sh` | the gates listed in its `gates` array, in order: currently `lint` | yes | | yes | yes | |

`scripts/check.sh` is the composite entry point: `ci.yml` runs it rather than the gates individually. There is no Python or Worker code yet, so there are no format, type-check or test gates; each is added to `scripts/check.sh`, `ci.yml` and this table in the PR that adds the code it checks.

Hooks are a tracked `.githooks/` directory, wired with `git config core.hooksPath .githooks` by `bash scripts/setup.sh`. Pre-commit checks only; it never rewrites files. It runs on the whole working tree, which takes under a second at present. Bypassing a hook is for a broken toolchain only; state the bypass and the equivalent checks in the PR.

Toolchain pins: none yet.

## Test policy

- Behaviour changes come with a test at the lowest layer that can show the behaviour; Git behaviour (exports, history checks, clone and pull) is tested against real repositories built in the test, not mocks.
- Documentation-only changes need no new tests; `docket/scripts/check-links.sh` covers their links.
- An empty or skipped suite is a failed gate.
- No automatic retries. A flaky test is filed in `TODO.md` with its evidence and fixed or quarantined by name.

## Review inputs

Read by `docket/CODE_REVIEW_GUIDE.md`, which links this section by its heading, so keep the heading as it is; a codebase review runs and records exactly what is listed here.

- Focus areas: the properties under [What quality means here](#what-quality-means-here) and the design in `docs/specs/`.
- Baseline commands beyond `bash scripts/check.sh`: none yet.
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
