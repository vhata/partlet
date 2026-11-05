# Partlet

Partlet lets you make individual projects in a private Git repository
public, while continuing to develop them in that same private
repository. Each project gets a read-only Git repository and a website
for browsing its files, reading its README, and downloading source
archives.

For example, suppose your private repository contains:

```text
my-monorepo/
├── tools/foo/       → publish as https://code.example.com/foo
├── libraries/bar/   → publish as https://code.example.com/bar
└── internal/        → keep private
```

Visitors can browse `https://code.example.com/foo/` or run:

```bash
git clone https://code.example.com/foo
```

That clone contains the contents and Git history of `tools/foo`, with
that directory becoming the repository root. Visitors can pull updates;
they cannot push changes back. Partlet does not provide issues or pull
requests. You choose which directories to publish.

## How it works

You review a project's exported history locally and approve its first
publication. A GitHub Action in your private repository then exports the
selected directories, scans their history for secrets, builds their web
pages, and uploads the result to Cloudflare R2. A Cloudflare Worker
serves those public files at your public site address. The Worker has no
access to your private repository.

**After the first publication, later fast-forward changes publish
automatically when you push to the configured branch.** Approval is not
a prompt for every update. History rewrites require explicit review.

**Publishing includes history**, including deleted files, commit
messages, and author names and emails. Messages can mention private
paths even when those files are excluded. Secret scanning helps find
credentials; you still need to decide whether the entire exported
history is suitable for public release.

## Get started

You need a private repository on GitHub with a full local clone, Git
2.31 or newer, and
[uv](https://docs.astral.sh/uv/getting-started/installation/). The local
commands below support macOS and Linux. Hosting also needs a Cloudflare
account with R2 enabled and Node/npm. You can use a default
`workers.dev` address or your own domain managed by Cloudflare; those
steps follow in the hosting guide. R2 and Workers are billable services.

### 1. Install Partlet

Run these commands in the directory where you keep your checkouts:

```bash
git clone https://github.com/vhata/partlet.git
cd partlet
PARTLET_REV="$(git rev-parse HEAD)"
bash scripts/install.sh --publisher-only
SOURCE_REPO=/absolute/path/to/my-monorepo
```

Replace `SOURCE_REPO` with your source checkout's absolute path. Keep
these shell variables for the following commands. Record `PARTLET_REV`
for the matching GitHub Action version later.

The installer uses uv to install an isolated Python 3.12 application and
put `partlet` on your PATH, then downloads the checksum-verified secret
scanner. If your shell cannot find `partlet`, run `uv tool update-shell`
and restart the shell. Installation does not install development hooks
or change tracked files. You can remove the Partlet checkout afterward.

Omit `--publisher-only` to install the Worker tools too; this requires
Node/npm as described in the [installation guide](docs/INSTALLATION.md).
That guide also covers installing directly from GitHub or a wheel,
dependency locations, upgrades, and multiple deployments.

### 2. Choose a project

Create `partlet.toml` at the root of your **source repository**:

```toml
[site]
source = "my-monorepo"
base_url = "https://code.example.com"
branch = "main"

[projects.foo]
path = "tools/foo"
description = "Foo command-line tool"
```

Replace the URL and project path with your own. The hosting guide
explains how to
[choose your public address](docs/GETTING_STARTED.md#2-create-storage-and-deploy-the-public-site),
including a `workers.dev` address if you do not own a domain. `foo`
becomes the public URL name; `source` is a stable internal storage name
for your monorepo. Use lowercase names without spaces. Add another
`[projects.NAME]` table for each additional project.

The selected directory must already be committed on the local `main`
branch (or the branch you set above). Partlet reads that branch's
committed history, including merged history, rather than uncommitted
files. If the directory moved in the past, declare its old locations
using [`previous_paths`](docs/PUBLISHING.md#manifest-reference).

### 3. Review and approve the first export

From the same terminal:

```bash
partlet review foo --repo "$SOURCE_REPO" --first-publish
```

Read the report, including deleted files, identities, commit messages,
and scan results. Exit the pager with `q` if one opens. Answer yes only
when that history is safe to publish. Partlet writes an `approved` hash
into your source repository's `partlet.toml`; leave that value to the
tool. This command does not upload anything and needs no cloud keys.
Repeat for any other projects you want to publish.

Use `--first-publish` only for a project's first publication. For an
existing project, omit it so review checks the public site's history.

### 4. Connect Cloudflare and enable publishing

Follow [Publish your first site](docs/GETTING_STARTED.md). It walks
through creating the bucket, configuring and deploying the Worker,
adding GitHub secrets and the publishing workflow, committing the
approval, and verifying your first public clone.

## Everyday use

Run `partlet` for a command overview and examples, or add `--help` to
any command for its options and examples:

```bash
partlet review --help
partlet worker
partlet worker preview --help
```

After setup, commit and push changes to your source repository's
publishing branch as usual. Check its **Actions → Partlet** run and
summary, then browse the site or `git pull` a public clone. Public
repositories use a `main` branch even if your source branch has another
name.

To add a project, add its manifest table, review it locally, then commit
and push the approval. To move a project or change author mapping,
[review the changed export](docs/PUBLISHING.md#review-and-approval)
before pushing the new configuration.

To stop publishing a project, removing its manifest entry stops updates
but leaves the existing public copy available. Follow the
[removal instructions](docs/PUBLISHING.md#removing-a-project) to delete
that copy too. If a macOS clone hangs, see
[Git troubleshooting](docs/PUBLISHING.md#macos-clone-hangs-over-http2).

## More documentation

- [Publish your first site](docs/GETTING_STARTED.md): Cloudflare and
  GitHub setup, then first-clone verification.
- [Installation and upgrades](docs/INSTALLATION.md): installed tools,
  independent deployment configs, and migration from an edited checkout.
- [Publishing reference](docs/PUBLISHING.md): manifest fields, CLI and
  Action options, history changes, removal, and recovery.
- [Worker guide](worker/README.md): local previews and HTTP behavior.
- [Design decisions](docs/DECISIONS.md): implementation trade-offs.

## Development and validation

To work on Partlet itself, use Python 3.12, uv, Git, shellcheck, Node
from [worker/.node-version](worker/.node-version), and npm >=11.19. From
the Partlet checkout:

```bash
bash scripts/setup.sh
bash scripts/check.sh
bash scripts/e2e.sh
```

Development setup installs Python development dependencies, the scanner,
Worker dependencies, and Git hooks shared by this clone's worktrees. The
checks use synthetic repositories and local simulated services; they
need no cloud credentials. See [Quality](docs/QUALITY.md).

Markdown is autoformatted when committing. If the hook changes a file,
review and stage it again before retrying. To format manually, run
`bash scripts/fmt-markdown.sh`.

To regenerate the Action dependency lock, run
`uv pip compile pyproject.toml --universal --generate-hashes --python-version 3.12 -o action/requirements.txt`
and review every changed version and hash.

## License

MIT. See [LICENSE](LICENSE).

Partlet is being built with help from
[Claude Code](https://claude.com/claude-code).
