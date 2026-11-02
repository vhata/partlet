# Publisher contracts

The publisher runs against a local clone of the source repository. Its
store keys are the interface consumed by the read-only Worker; the
Worker never needs the source repository or the publisher's credentials.

## Commands

Run `bash scripts/setup.sh` in each Partlet worktree. It creates a Python
3.12 `.venv` and installs the required tools. Use `.venv/bin/partlet` for
the commands below.

- `build --repo <source> --out <directory>` creates a local preview.
  Add `--scan` to scan its complete exported history before writing each
  project. Builds check the export tool versions even without scanning.
- `publish --repo <source>` publishes to R2 and always scans. HEAD must
  equal the local publishing branch tip and the manifest must match its
  committed contents. Configuration refusals exit 2; project, lock or
  store failures exit 1; successful or unchanged runs exit 0.
- `unpublish <name> --repo <source>` removes a project after it has been
  removed or unapproved in the manifest. Commit and push that manifest
  change first so the next publish cannot restore it. This command asks
  before deleting; `--yes` records explicit noninteractive consent.
- `unlock --repo <source>` reports the lock holder and asks before removing
  a stale lock. Verify that the holder has stopped first. `--yes` bypasses
  the prompt only after that verification.

All commands accept `--manifest <file>` in place of `<source>/partlet.toml`.
`unpublish` and `unlock` accept `--out <directory>` to act locally.
`build` and `publish` accept `--summary <file>`; otherwise they append to
`GITHUB_STEP_SUMMARY` when set. Summaries include project outcomes and
actual tool versions, with escaped and bounded reasons.

## Configuration and credentials

The [design specification](specs/2026-10-15-partlet-design.md) defines the
manifest and public store layout. Source and project names are stable
store namespaces. Approval pins name exported commits, not source commits.
A rewrite requires `allow_rewrite_of` naming the exact published tip.

R2 commands require these environment variables:

| Variable | Purpose |
| --- | --- |
| `PARTLET_R2_ACCOUNT_ID` | 32-character hexadecimal Cloudflare account ID |
| `PARTLET_R2_ACCESS_KEY_ID` | Bucket-scoped object read/write access key |
| `PARTLET_R2_SECRET_ACCESS_KEY` | Matching secret access key |
| `PARTLET_R2_BUCKET` | Existing bucket name |
| `PARTLET_R2_ENDPOINT` | Optional endpoint override, replacing account ID |

The default endpoint is `https://<account>.r2.cloudflarestorage.com`.
An override supports jurisdiction endpoints and loopback S3 simulation.
Endpoints require HTTPS, with plain HTTP allowed only on loopback.
Embedded URL credentials, paths, queries and fragments are refused.
The access key and secret are removed from the process environment before
any Git, filter-repo or gitleaks subprocess starts. Error output and object
representations do not include credentials. Test runs strip ambient cloud
credentials and use fake keys against a local S3 simulator.

The publisher requires Git 2.31 or newer, git-filter-repo 2.47.0 exactly,
and gitleaks 8.30.1 exactly for scanning. It records the actual Git version;
this does not establish identical exports across different Git versions.
The source root's `.gitleaks.toml` and `.gitleaksignore` apply to exported
paths and native fingerprints. All commits reachable from the export tip
are scanned, including side branches and merges. Findings block project
writes and leave that project's published state unchanged.

## Serialization and recovery

Every CLI build, publish and unpublish holds `<source>/lock` for the entire
operation, including site-index writes and cleanup. Automation must also
serialize runs for the same source, using a concurrency group with
cancellation disabled. The store lock covers local and other workflows
that a single workflow's concurrency group cannot see.

A held lock fails closed. It never expires automatically. Normal errors,
Ctrl-C and SIGTERM run lock cleanup; SIGKILL or a lost process can leave a
lock behind. Use `unlock` only after verifying the recorded holder stopped.
Removing a live holder's lock can race an in-progress publish.

R2 deletes make one request attempt. If a successful response is lost,
the outcome remains unknown and the command fails. Do not automatically
retry lock deletion: another publisher may already hold a replacement
lock. Inspect the holder and establish that it has stopped before explicit
recovery. If the failed delete did not land, the old lock remains and
blocks subsequent runs.

Immutable uploads precede live pointers. Superseded objects receive one
publish of grace, and later runs sweep unreachable uploads left by an
interruption. An interrupted publish can be retried after safe lock
recovery. Unpublish removes `current` and refreshes the site index before
retiring the remaining project objects; retrying finishes a partial
unpublish. No automatic CI unpublish feature is provided.

## User-run setup

Bucket creation, credential creation, Worker deployment, GitHub secrets,
account settings and releases remain user-run operations. The plan's
[user-run steps](../plans/2026-10-17-r2-publishing.md#user-run-steps)
describe them, including which operations are billable. Local synthetic
and S3-simulation tests establish publisher behavior only; they do not
establish hosted R2, Worker or private-repository behavior.
