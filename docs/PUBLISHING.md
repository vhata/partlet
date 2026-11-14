# Publishing reference

Start with the [README](../README.md) to install Partlet and choose a
project, then follow [Getting started](GETTING_STARTED.md) to put it
online. This reference covers configuration, commands, automation and
recovery after setup.

The publisher reads a local clone of your source repository, exports
each selected directory's Git history and writes public Git data and
site pages. The read-only Worker serves those objects from R2. It never
needs your private repository or the publisher's write credentials.

## Manifest reference

Keep `partlet.toml` at the root of your source repository. A complete
commented [example manifest](../examples/partlet.toml) is available to
copy. For site appearance and homepage setup, follow
[Configure your site](SITE.md). For example:

```toml
[site]
source = "my-source"
base_url = "https://partlet.example.com"
# name = "Example projects" # defaults to the base URL hostname
# tagline = ""             # optional plain-text footer text
# readme = "public/home.md" # explicit additional public Markdown input
branch = "main"
# mailmap = "public.mailmap"

[projects.foo]
path = "tools/foo"
description = "Foo command-line tool"
# previous_paths = ["old-tools/foo"]
# approved is written by `partlet review`; do not copy a source commit SHA.
```

Add a `[projects.NAME]` table for each public project. The directory's
contents appear at the root of its exported repository. Only the
selected publishing branch is exported; public repositories use a `main`
branch.

| Field | Meaning |
| -- | -- |
| `site.source` | Required stable storage namespace for this monorepo. Match the Worker's `SOURCE` and workflow concurrency group. |
| `site.base_url` | Required public site URL, including `https://`, used for links and clone URLs. |
| `site.name` | Optional display name linked to the site root; defaults to the hostname in `site.base_url`. |
| `site.tagline` | Optional plain text shown at the left of the footer; defaults to empty. |
| `site.readme` | Optional committed source-repository-relative Markdown file for the homepage introduction; absent means no introduction. See the homepage policy below. |
| `site.branch` | Source branch to export; defaults to `main`. It must exist locally. Match the workflow's push branch. |
| `site.mailmap` | Optional path to an author/committer identity mapping file, relative to the source checkout. |
| `site.theme.name` | Bundled theme: `classic` (default), `paper`, or `terminal`. Mutually exclusive with `site.theme.path`. |
| `site.theme.path` | Vendored theme directory, relative to the manifest, committed on `site.branch`. |
| `site.theme.mode` | `auto` (default), `light`, or `dark`. |
| `projects.NAME.path` | Required current project directory, relative to the source root. |
| `projects.NAME.description` | Optional description displayed on the site. |
| `projects.NAME.previous_paths` | Optional list of earlier directory locations to include in the same export. Defaults to `[]`. |
| `projects.NAME.approved` | Exported commit hash written by `partlet review`. Without it, the project is skipped. |
| `projects.NAME.allow_rewrite_of` | Exact currently published commit whose replacement was authorized by `review --allow-rewrite`. |

Source and project names use lowercase letters, digits, `.`, `_` and
`-`, beginning with a letter or digit. Project names cannot end in
`.git`. Quote project names containing dots in TOML, for example
`[projects."my.tool"]`. Treat these names as stable: changing them
creates a different storage namespace; it does not move or remove an
existing publication.

`path` and `previous_paths` name directories, not files or glob
patterns. Use forward slashes, without `.` or `..` components. They
cannot contain `:` because git-filter-repo uses it to separate source
and destination in path renames. Colons in file names inside a supported
project path remain supported. The current directory must exist on
`site.branch`, even when only its old locations contain history.

### Approval and later updates

Approval enables publication; it does **not** freeze the project at the
approved commit or require a person to approve every later commit. First
publication includes the current export tip if the approved commit is in
its history. Later fast-forward updates publish automatically. Every
update that writes project content is scanned for secrets first. An
unchanged run can return without repeating the scan.

To keep something private, keep it outside the declared project paths
and their history, and out of explicitly selected public inputs such as
`site.readme`. Files deleted years ago, commit messages and author
identities can still be public. Secret scanning helps find credentials;
it does not decide whether all the historical content is suitable for
publication. The [homepage policy](#site-identity-and-homepage) has a
separate approval and scanning boundary.

Re-run review when adding a project, changing exported paths or changing
identity mappings. To move `tools/foo` to `packages/foo`, set the new
`path`, add `tools/foo` to `previous_paths` and review again. Earlier
locations are not followed automatically. Use a Git mailmap file to
change public identities; changing that mapping can rewrite exported
history and require explicit rewrite approval.

## Commands

Run these from any directory after the
[README installation](../README.md). Replace `/path/to/source` with an
absolute path to your separate source checkout. The CLI uses
`partlet.toml` there by default. Without `--repo`, it uses the current
directory as the source checkout.

Run `partlet` (or `partlet --help`) for a workflow overview. Every
command has its own `--help`, including examples; `partlet worker` lists
the Worker commands. These help commands need no configuration,
installed external tools or cloud credentials.

| Command | Effect |
| -- | -- |
| `partlet review foo --repo /path/to/source` | Inspect exported history and, after confirmation, write approval into the local manifest. |
| `partlet preview --repo /path/to/source` | Build all configured projects and browse them locally without approval, cloud access or deployment config. |
| `partlet build --repo /path/to/source --out /path/to/output --scan` | Scan and build approved projects into a local directory, without R2 access. |
| `partlet publish --repo /path/to/source` | Scan and publish approved projects to R2 using the credentials below. |
| `partlet unpublish foo --repo /path/to/source` | Confirm and delete the project's stored data, then rebuild the site index. |
| `partlet unlock --repo /path/to/source` | Report the publisher lock holder and confirm removal of a stale lock. |
| `partlet theme list` | List the bundled site themes without cloud access. |
| `partlet theme check --repo /path/to/source` | Validate the selected theme using committed publishing-branch inputs. |

`review`, `preview` and `build` export the local `site.branch`,
including its committed history; uncommitted project edits are not
exported. Update that branch before reviewing. `publish` additionally
requires HEAD to equal its local publishing branch tip and the manifest
to match its committed contents. A shallow source checkout is refused.
These local checks do not fetch or verify a remote branch tip.

`preview` uses fresh temporary output and local simulated R2, with clone
URLs pointing at localhost. It reads the current manifest without
modifying approvals, including projects with missing or stale approvals.
It needs the Worker tools (`partlet setup --worker`) but no hosting
configuration. Stop with Ctrl-C and rerun to pick up changes; there is
no automatic rebuild. `--port` defaults to 8787. Add `--scan` to check
history before serving; preview skips scanning by default and does not
replace publication review. Its temporary output is removed on normal
shutdown, including Ctrl-C and SIGTERM.

`build` without `--scan` skips secret scanning. Its output contains
internal storage keys, not an ordinary website root. Use the
[local Worker preview](../worker/README.md#preview-local-publisher-output)
to browse it or clone through the same routes as the public site.

All publisher commands accept `--manifest <file>` to use another
manifest path; relative paths are resolved from the command's working
directory. `unpublish` and `unlock` accept `--out <directory>` to
operate on a local store instead of R2. Both ask for confirmation;
`--yes` bypasses the prompt for automation after you have verified the
intended action.

`build` and `publish` accept `--summary <file>`; otherwise they append
to `GITHUB_STEP_SUMMARY` when set. Summaries contain project outcomes,
actual tool versions and bounded, escaped failure reasons. Configuration
refusals exit 2; project, lock or store failures exit 1; successful,
unchanged or skipped-only runs exit 0. Check individual outcomes: a
green run with every project `skipped` has published nothing.

See [Site themes](THEMES.md) for theme selection, third-party
installation, local previews, compatibility and the public-asset
contract. Deploy the matching Worker before publishing themed pages on
an existing site.

The installed tool also provides `partlet setup [--worker]` for explicit
dependency installation, and `partlet worker` commands for independent
Wrangler configurations, local preview, and user-run deployment. See
[installation](INSTALLATION.md), [upgrades](UPGRADING.md) and the
[first-site guide](GETTING_STARTED.md). These commands do not use the
publisher's `--manifest` option or R2 write credentials.

## Review and approval

For a project's first publication:

```bash
partlet review foo --repo /path/to/source --first-publish
```

For a project already on your public site:

```bash
partlet review foo --repo /path/to/source
```

The report shows the export tip, every historical path (with deletions
marked), oversized historical files, authors, committers, full commit
messages, secret findings with native fingerprints, and possible earlier
directory locations missing from `previous_paths`. Inspect that content
before answering yes.

The default command reads the published tip from the public site's
`<base_url>/<name>/info/refs` and needs no R2 credentials. When the site
is unavailable, use `--published-tip <full-sha>` with its known
published tip. `--first-publish` skips that lookup and asserts that the
project has never been published. The older spelling
`--published-tip none` has the same effect and remains supported; use
only one of these options. For an existing publication, use its known
tip or the default public-site lookup. A malformed or ambiguous refs
response fails the review.

Review scans the full exported history using the source root's gitleaks
configuration. Findings prevent approval. A non-fast-forward export
requires `--allow-rewrite`; that writes `allow_rewrite_of` naming the
exact published tip. This intentionally replaces public history and can
require readers to clone again. The flag still asks for approval, and
there is no noninteractive approval switch. EOF, an empty answer or a no
answer does not approve.

A yes answer writes `approved` while preserving manifest comments,
layout, line endings and permissions. Invalid edits leave it untouched.
A manifest changed during published-tip lookup or while answering needs
a fresh review. Commit and push the approval before automated
publishing. Review modifies only the local manifest and takes no store
lock.

## GitHub Action

Copy [examples/partlet.yml](../examples/partlet.yml) into the source
repository's `.github/workflows/partlet.yml`. Replace `SOURCE` with
`site.source`, `PARTLET_RELEASE_SHA` with the full commit hash of the
Partlet version you selected, and `main` if your publishing branch has
another name. Use the same Partlet version locally for review. You do
not need to create release tags in Partlet to use the Action.

The workflow first runs `actions/checkout` to download the source
repository, then `vhata/partlet` to publish from that checkout. Each
step's `with:` block configures only that action. Keep `fetch-depth: 0`
and `persist-credentials: false` in **the checkout step's `with:`
block**; they control Git history and checkout's GitHub credentials. The
Partlet step's `with:` block takes the publishing inputs listed below,
including the separate R2 credentials. The first-site guide
[maps each setting to its location](GETTING_STARTED.md#4-add-the-publishing-workflow).

Keep workflow-level `permissions` set to `contents: read` and
`concurrency` set to `cancel-in-progress: false`. All workflows
publishing the same source must use the same concurrency group. Avoid
pull-request triggers: publication requires HEAD at the local publishing
branch tip and an exactly committed manifest. The source lock also
covers callers outside this workflow and never expires automatically.

The Action supports Linux x64 and ARM64 runners; the example uses
`ubuntu-24.04`. A detached checkout is supported if it equals the
publishing tip: the Action creates a missing local branch from
`origin/<branch>` without fetching or changing an existing branch.
Shallow history is rejected.

| Input | Value |
| -- | -- |
| `account-id` | Cloudflare account ID from `PARTLET_R2_ACCOUNT_ID`. |
| `access-key-id` | Bucket-scoped object read/write key from `PARTLET_R2_ACCESS_KEY_ID`. |
| `secret-access-key` | Matching secret from `PARTLET_R2_SECRET_ACCESS_KEY`. |
| `bucket` | Existing bucket name from `PARTLET_R2_BUCKET`. |
| `endpoint` | Optional R2 S3 endpoint override, for example a jurisdiction endpoint. |
| `repo` | Source checkout path; defaults to `.`. |
| `manifest` | Manifest path relative to that checkout; defaults to `partlet.toml`. |
| `local-out` | Test-only local output directory; scans and builds without R2 while retaining checkout and committed-manifest checks. |

Pass credentials through the Action's inputs as in the example. Only its
publishing step receives them. Do not put them in job-level `env`.

The selected Action checkout supplies Partlet's code. It installs Python
3.12, checksum-verified uv 0.13.5 and gitleaks 8.30.1, and hash-locked
wheels including git-filter-repo 2.47.0. No package build backend or
source-repository code is installed. Its isolated Python launcher
excludes the source checkout and clears inherited Python import
configuration before child tools. Setup runs in the Action directory
with uv configuration and caches disabled. Git comes from the runner
image; actual tool versions are recorded in the summary.

## Configuration and credentials

R2 CLI commands require the following environment variables. The Action
sets these from its inputs; local `publish`, `unpublish` and `unlock`
need them in your shell. `review` and local `build` do not need cloud
credentials. Partlet does not automatically load a `.env` file.

| Variable | Purpose |
| -- | -- |
| `PARTLET_R2_ACCOUNT_ID` | 32-character hexadecimal Cloudflare account ID |
| `PARTLET_R2_ACCESS_KEY_ID` | Bucket-scoped object read/write access key |
| `PARTLET_R2_SECRET_ACCESS_KEY` | Matching secret access key |
| `PARTLET_R2_BUCKET` | Existing bucket name |
| `PARTLET_R2_ENDPOINT` | Optional endpoint override, replacing account ID |

The default endpoint is `https://<account>.r2.cloudflarestorage.com`. An
override supports jurisdiction endpoints and loopback S3 simulation.
Endpoints require HTTPS, with plain HTTP allowed only on loopback.
Embedded URL credentials, paths, queries and fragments are refused. The
access key and secret are removed from the process environment before
any Git, filter-repo or gitleaks subprocess starts. Error output and
object representations do not include credentials. Test runs strip
ambient cloud credentials and use fake keys against a local S3
simulator.

### Secret scanning and tool versions

The publisher requires Git 2.31 or newer, git-filter-repo 2.47.0
exactly, and gitleaks 8.30.1 exactly for scanning. It records the actual
Git version; this does not establish identical exports across different
Git versions. The source root's `.gitleaks.toml` and `.gitleaksignore`
apply to exported paths and native fingerprints. All commits reachable
from the export tip are scanned, including side branches and merges.
Findings block project writes and leave that project's published state
unchanged.

Deleting a secret from the latest version is insufficient if it remains
in exported history. Remove it from the history before approving, and
rotate any exposed credential. For a verified false positive, use the
source root's gitleaks configuration or the exact reported fingerprint
in `.gitleaksignore`, then review again. A finding can have several
fingerprints when it appears in both an original commit and a merge.

## Removing a project

After upgrading Partlet, complete the
[applicable migration](UPGRADING.md#semantic-output-version-1-migration)
before removing a project. The semantic-output upgrade requires a
successful publication to update stored theme metadata first.

Removing a project from the manifest stops future publication but does
not delete the copy already stored. Remove its `[projects.NAME]` table,
commit and push that change first, and verify any earlier publishing run
has stopped. Set the R2 variables above, then run:

```bash
partlet unpublish foo --repo /path/to/source
```

The command shows the target and asks before deleting. It removes all
stored project objects, including retained packs, and updates the site
index. Existing clones and downloads cannot be recalled. Already cached
pages, raw files or archives can remain visible until their cache
lifetime expires.

## Serialization and recovery

Every CLI build, publish and unpublish holds `<source>/lock` for the
entire operation, including site-index writes and cleanup. Automation
must also serialize runs for the same source, using a concurrency group
with cancellation disabled. The store lock covers local and other
workflows that a single workflow's concurrency group cannot see.

A held lock fails closed. It never expires automatically. Normal errors,
Ctrl-C and SIGTERM run lock cleanup; SIGKILL or a lost process can leave
a lock behind. Run `unlock` to see the recorded holder, verify that run
has stopped, then confirm removal. Removing a live holder's lock can
race an in-progress publish.

R2 deletes make one request attempt. If a successful response is lost,
the outcome remains unknown and the command fails. Do not automatically
retry lock deletion: another publisher may already hold a replacement
lock. Inspect the holder and establish that it has stopped before
explicit recovery. If the failed delete did not land, the old lock
remains and blocks subsequent runs.

Immutable uploads precede live pointers. Superseded site builds and
archives receive one publish of grace. Pack and index objects
additionally remain for at least one hour after a sweep first observes
them outside the live and previous pack lists. This includes abandoned
uploads. Retirement times are persisted in `retired-packs.json` before
deletion; retries and unchanged runs reuse them. A revived object loses
its timer, so a later retirement gets a fresh hour. Invalid state fails
closed. An interrupted publish can be retried after safe lock recovery.
Unpublish removes `current` and refreshes the site index before retiring
the remaining project objects; retrying finishes a partial unpublish. No
automatic CI unpublish feature is provided.

Mutable Git metadata (`HEAD`, `info/refs`, `objects/info/packs`) uses
`no-store`: independent cache ages must not combine a fresh tip with an
older pack list that cannot contain it. Retention additionally protects
in-flight fetches and legacy metadata cached under the former policy.
The one-hour pack window covers that former 60-second freshness plus up
to 59 minutes for a client to finish fetching advertised objects. It
starts conservatively after an object leaves both pack lists, rather
than at its upload time. An unchanged publication sweeps expired
objects; without another run they remain stored. A client paused beyond
that window may need to retry with fresh metadata. Clock rollback delays
cleanup. Unpublish deliberately removes all project objects, including
retained packs, and invalidates Git fetches that still need them. An
explicitly approved history rewrite also changes the advertised
snapshot; clients racing it may need to fetch again from fresh metadata.

When upgrading an existing deployment, deploy the Worker with `no-store`
first and let all previously served 60-second metadata entries expire
before the first rapid publication. Do not override these headers with
edge cache rules. Local checks cannot establish the deployed policy.

`bash scripts/e2e.sh` exercises CLI review, committed approval,
publication against loopback S3, an exact mirror into local R2, public
Worker clone and pull, browsing/raw/archive routes, unchanged
publication, secret rejection and CLI unpublish. Its cache regression
freezes A's public metadata while B and C consolidate and then clones A
through public Worker object URLs. An additional cache obeys the actual
response headers: warm only A's pack list, then clone the latest refs
after consolidation. `no-store` prevents that cache from mixing fresh
refs with a stale pack list. The synthetic fixture lowers the pack-count
threshold to trigger consolidation quickly; production keeps its
existing threshold. No internal storage URL substitutes for a public
route. This proves local interface compatibility, not hosted R2/Worker
consistency or edge behavior.

## macOS clone hangs over HTTP/2

A live synthetic trial reproduced a hanging plain `git clone` with an
older Homebrew Git 2.56.0 package linked to Apple's libcurl 8.7.1.
Expected 404 probes for missing loose objects and alternates triggered
HTTP/2 errors and corrupted subsequent headers. Partlet publishes packed
objects, so those probes are normal Git transport behavior. Upstream
reports a related error-handling regression in
[curl issue 13411](https://github.com/curl/curl/issues/13411).

**Upgrade Git itself.** Homebrew Git `2.56.0_2` switched to maintained
curl. That package, linked to libcurl 8.23.0, passed a fresh clone and
an incremental pull after another hosted publication, negotiating HTTP/2
with no HTTP-version settings or loader overrides. See the
[Homebrew package change](https://github.com/Homebrew/homebrew-core/commit/5af25e905526dc43c557a3d2a5e2ef14e4bfe60b).

For a Homebrew installation:

```bash
brew update
brew upgrade git
hash -r
```

Check the installed package revision and the library used by the active
Git HTTP helper:

```bash
brew list --versions git
git version --build-options
otool -L "$(git --exec-path)/git-remote-https"
```

The verified package reports `git 2.56.0_2` and links
`/opt/homebrew/opt/curl/lib/libcurl.4.dylib`. The prefix can differ on
other installations. `git --version` alone reports `2.56.0` for both
package revisions. Updating standalone curl does not change Git's
existing system-library linkage.

Retry a fresh plain clone after upgrading. For an existing clone where
you saved the temporary HTTP/1.1 setting, remove it before verifying a
pull after a new publication:

```bash
git -C YOUR_CLONE config --unset http.version
```

Run that unset command only if the clone has the setting; an absent key
returns a nonzero status. Verification also requires no global or
per-command HTTP-version setting and no diagnostic loader override.

If upgrading is unavailable, a temporary workaround is a fresh clone
using HTTP/1.1:

```bash
git -c http.version=HTTP/1.1 clone \
  --config http.version=HTTP/1.1 \
  https://YOUR_SITE/YOUR_PROJECT YOUR_PROJECT-http1
```

The first option applies to cloning; `--config` also saves the setting
in the resulting repository for later fetches and pulls. For an existing
clone, set it locally:

```bash
git -C YOUR_CLONE config http.version HTTP/1.1
```

These workaround commands do not change the global Git configuration.
The upgraded package meets the
[plain clone and pull requirement](QUALITY.md#what-quality-means-here)
for the verified client; the temporary workaround alone does not. Other
Git/library combinations need their own verification. Local HTTP smoke
tests do not cover Cloudflare's HTTP/2 connection behavior.

## Site identity and homepage

For a step-by-step setup, example Markdown, preview instructions and
editing/removal tasks, see [Configure your site](SITE.md). This section
defines the input and publication rules.

`site.name` sets the linked header name; its default is the hostname in
`site.base_url`. `site.tagline` is optional plain text in the footer,
empty by default. Both values are escaped, never interpreted as HTML.

Set `site.readme = "public/home.md"` to render an introduction above the
project list. This is an explicit additional public input, outside the
project exports. Selecting the file authorizes publication of its
current committed contents independently of project approvals, even when
no projects are approved or configured. Later committed edits are
published without a new project approval. Homepage content is not passed
through project secret scanning: neither production publication nor
`build --scan` or `preview --scan` scans this file. Review it for
secrets and other private material before selecting it and before
publishing changes. No root README is automatically selected. The file
must be committed on `site.branch`, be UTF-8 regular Markdown (`.md` or
`.markdown`), and use a path relative to the source repository, without
absolute paths, traversal or symlinks. Builds and previews read
committed bytes; production also refuses dirty input files. An absent
setting means no introduction.

Homepage Markdown uses the same inert renderer as project READMEs. Raw
HTML is escaped and script URLs are suppressed. Links and images may use
public root-relative URLs, fragments, or absolute HTTP(S) URLs; links
also allow `mailto:`. Use HTTPS for external images: the Worker blocks
external HTTP images. Fragment links need an existing target; Markdown
headings do not receive automatic IDs. Protocol-relative and ambiguous
relative references are rejected with an actionable error. Rewrite them
to public URLs. Partlet never follows those references to copy private
files or assets.

Identity changes regenerate project pages without changing exported Git
history or approval pins. Homepage-only edits regenerate the index; they
do not rebuild unchanged project pages. Publication stores only the
public display strings and rendered introduction, never its source path.
Removal and index recovery use this validated durable presentation even
when the source file is unavailable or the local configuration changes.
During partial publication, failed projects retain their previous pages
and identity while the index adopts the selected site presentation.
