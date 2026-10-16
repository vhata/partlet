# Partlet: agent guide

Partlet publishes selected directories of a private monorepo as public, read-only Git repositories with a static website, served from Cloudflare R2 by a Worker. Design specs go in `docs/specs/` and implementation plans in `plans/`.

<!-- docket:begin -->

## Docket

This project is run with docket. Read [docket/CONTRACT.md](docket/CONTRACT.md) before any work; it is the authoritative workflow, and this section records only this project's settings. The installer keeps this section current: the text above the list is rewritten on every run, the list keeps the values this project has set, and the section may sit anywhere in this file.

- Queue areas: `[PUBLISHER]`, `[SITE]`, `[WORKER]`, `[ACTION]`, `[TOOLING]`, `[DOCS]`.
- Concurrency cap: none.
- Merging and releases: the user merges unless delegated in the turn. Release tags (such as the action's `v1`), Worker deploys and any Cloudflare or GitHub settings change are the user's.
- Optional pieces in force: stacked PRs. Deferred: review ledger (installed, no review until the user requests one), scheduled validation of main (until there is code worth an extended run), roadmap queue.
- Environment: Python 3.12; each worktree has its own `.venv`. Agents never provision, deploy to or change billable services (Cloudflare R2, Workers); they write the code and the instructions and the user runs them.
- Commit identity: this repository commits as `jonathan.hitchcock@gmail.com` (`git config user.email` in the clone).
- Attribution: no AI attribution in commits, PR bodies or review threads (no `Co-Authored-By` trailers, no "Generated with" footers). The README credits Claude once; that is the only place.
- Drafts first: until the user lifts this rule, show the user a draft of any new or changed repository file before committing it.

<!-- docket:end -->

## Working here

- Run `bash scripts/setup.sh` once per clone or worktree; it installs the git hooks.
- Run `bash scripts/check.sh` before opening or updating a PR. What it covers is in [docs/QUALITY.md](docs/QUALITY.md).
- Non-obvious choices and their reasons are in [docs/DECISIONS.md](docs/DECISIONS.md). Read the relevant entry before changing a mechanism that looks odd.
