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

## Review and approval

Run `.venv/bin/partlet review <name> --repo <source>` before the first
publication and whenever changing exported paths or author mapping.
The report shows the export tip, every historical path (with deletions
marked), oversized historical files, authors, committers, full commit
messages, secret findings with native fingerprints, and possible earlier
directory locations missing from `previous_paths`.

The command reads the published tip from the public site's
`<base_url>/<name>/info/refs` and needs no R2 credentials. When the site
is unavailable, use `--published-tip <full-sha>`; for a first publication,
use `--published-tip none`. A malformed or ambiguous refs response fails
the review.

Review scans the full exported history using the source root's gitleaks
configuration. Findings prevent approval. A non-fast-forward export
requires `--allow-rewrite`; that writes `allow_rewrite_of` naming the
exact published tip. The flag still asks for the user's approval answer,
and there is no noninteractive approval switch. EOF, an empty answer or
a no answer does not approve.

A yes answer writes `approved` in the manifest while preserving comments,
layout, line endings and permissions. Invalid edits leave it untouched.
A manifest changed during published-tip lookup or while answering needs
a fresh review. Commit and push the approval pin before publishing.
Review modifies only the local manifest and takes no store lock.

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

Immutable uploads precede live pointers. Superseded site builds and
archives receive one publish of grace. Pack and index objects additionally
remain for at least one hour after a sweep first observes them outside
the live and previous pack lists. This includes abandoned uploads.
Retirement times are persisted in `retired-packs.json` before deletion;
retries and unchanged runs reuse them. A revived object loses its timer,
so a later retirement gets a fresh hour. Invalid state fails closed.
An interrupted publish can be retried after safe lock
recovery. Unpublish removes `current` and refreshes the site index before
retiring the remaining project objects; retrying finishes a partial
unpublish. No automatic CI unpublish feature is provided.

Mutable Git metadata (`HEAD`, `info/refs`, `objects/info/packs`) uses
`no-store`: independent cache ages must not combine a fresh tip with an
older pack list that cannot contain it. Retention additionally protects
in-flight fetches and legacy metadata cached under the former policy.
The one-hour pack window covers that former 60-second freshness plus up
to 59 minutes for a client to finish fetching advertised objects.
It starts conservatively after an object leaves both pack lists, rather
than at its upload time. An unchanged publication sweeps expired objects;
without another run they remain stored. A client paused beyond that window
may need to retry with fresh metadata. Clock rollback delays cleanup.
Unpublish deliberately removes all project objects immediately, including
retained packs, and invalidates existing URLs and in-flight fetches. An
explicitly approved history rewrite also changes the advertised snapshot;
clients racing it may need to fetch again from fresh metadata.

When upgrading an existing deployment, deploy the Worker with `no-store`
first and let all previously served 60-second metadata entries expire
before the first rapid publication. Do not override these headers with
edge cache rules. Local checks cannot establish the deployed policy.

`bash scripts/e2e.sh` exercises CLI review, committed approval, publication
against loopback S3, an exact mirror into local R2, public Worker clone and
pull, browsing/raw/archive routes, unchanged publication, secret rejection
and CLI unpublish. Its cache regression freezes A's public metadata while
B and C consolidate and then clones A through public Worker object URLs.
An additional cache obeys the actual response headers: warm only A's
pack list, then clone the latest refs after consolidation. `no-store`
prevents that cache from mixing fresh refs with a stale pack list.
The synthetic fixture lowers the pack-count threshold to trigger
consolidation quickly; production keeps its existing threshold.
No internal storage URL substitutes for a public route. This proves local
interface compatibility, not hosted R2/Worker consistency or edge behavior.

## User-run setup

Bucket creation, credential creation, Worker deployment, GitHub secrets,
account settings and releases remain user-run operations. The plan's
[user-run steps](../plans/2026-10-17-r2-publishing.md#user-run-steps)
describe them, including which operations are billable. Local synthetic
and S3-simulation tests establish publisher behavior only; they do not
establish hosted R2, Worker or private-repository behavior.
