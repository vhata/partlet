# Configure your site

Your site's name, footer text and optional introduction belong in
`partlet.toml` in your **source repository**. `wrangler.toml` configures
hosting; it does not control these page contents. These settings work
with Classic, Paper, Terminal and third-party format-2 themes. Choose
colors and typography separately in the [theme guide](THEMES.md).

The homepage always includes the project list. Project descriptions come
from each `[projects.NAME]` table. An optional Markdown introduction
appears above that list; it does not replace it. Project READMEs still
appear on their own project pages.

## 1. Set the name and footer

Edit your existing `[site]` table, or start from the commented
[example manifest](../examples/partlet.toml). For example:

```toml
[site]
source = "my-monorepo"
base_url = "https://code.example.com"
branch = "main"
name = "My projects"
tagline = "Tools and experiments"
# readme = "public/home.md"

[projects.foo]
path = "tools/foo"
description = "Foo command-line tool"
```

Use your own public URL, namespace, branch and project path. Preserve
existing project approvals when editing a working manifest.

| Setting | What visitors see | If omitted |
| -- | -- | -- |
| `site.name` | Header link back to the homepage | Hostname from `site.base_url` |
| `site.tagline` | Plain text in the footer | No tagline |
| `site.readme` | Markdown introduction above the homepage project list | No introduction |

Name and tagline are plain text, not Markdown or HTML. The separate
“Published with Partlet” footer link goes to the Partlet project page;
it is not a configurable site link.

Put these keys inside `[site]`, before `[site.theme]` or a
`[projects.NAME]` table. In TOML, a key belongs to the most recent
table: `name` under `[site.theme]` chooses the theme, not the site name.
`site.source` is a storage namespace, not a display name; do not change
it to rename your site.

## 2. Add an introduction, if you want one

Create `public/home.md` inside your source repository. You can copy the
[example homepage](../examples/home.md), or write a short introduction:

```markdown
## About these projects

These are tools I maintain and use.
Start with [Foo][foo], or visit [my website](https://example.com/).

[foo]: /foo/
```

Then uncomment `readme = "public/home.md"` in `[site]`. You may select
`README.md` instead, but Partlet never selects a root README for you.
The selected file must be UTF-8 Markdown (`.md` or `.markdown`), a
regular file, and committed on `site.branch`. Its path is relative to
the source repository root, even with an alternate manifest location.
Absolute paths, `..` and symlinks are rejected.

**Selecting the file authorizes publication of its current contents
independently of project approvals, even with no approved projects.**
Later committed edits publish without another approval. This file is not
secret-scanned by publication, `build --scan`, or `preview --scan`.
Review it yourself before selecting it and before publishing changes.
Only the selected file's current contents become the introduction, not
its Git history. It is not added to project clones or archives unless it
is also inside an exported project directory.

Links must point to public destinations:

| Example | Behavior |
| -- | -- |
| `/foo/` | Links to an already published project, or its local preview |
| `[Website](https://example.com/)` | Links to an external page |
| `[Email](mailto:hello@example.com)` | Opens the visitor's mail application |
| `![Logo](https://example.com/logo.png)` | Loads an image already hosted at that public URL |
| `notes.md` or `images/logo.png` | Rejected; these relative paths do not identify a public destination |

Root-relative URLs start at your public site, not your source checkout.
For example, `/images/logo.png` only works if that URL is actually
served; creating `images/logo.png` in the private repository does not
publish it. Partlet does not copy linked files or upload homepage
assets. Raw HTML is displayed as text. See the
[homepage reference](PUBLISHING.md#site-identity-and-homepage) for the
complete rendering and URL rules.

## 3. Commit the content and preview

Use the source checkout and the branch selected by `site.branch` (`main`
in these examples). Commit only the intended public file and manifest:

```bash
SOURCE_REPO=/absolute/path/to/my-monorepo
git -C "$SOURCE_REPO" branch --show-current
# Confirm this is the branch selected by site.branch before committing.
git -C "$SOURCE_REPO" add partlet.toml public/home.md
git -C "$SOURCE_REPO" commit -m 'Configure public site'
partlet preview --repo "$SOURCE_REPO"
```

Omit `public/home.md` from `git add` if you did not select an
introduction. Preview needs Node/npm and a one-time
`partlet setup --worker`; see [installation](INSTALLATION.md). No cloud
account or publication approval is needed for preview.

Open `http://127.0.0.1:8787/`. Check the header name, footer,
introduction and its links, then open a project and check its header and
footer too. The introduction belongs only on the homepage. Preview
includes all configured projects, even unapproved ones; production lists
published projects. Only link to projects you intend to publish.

Preview reads the current manifest but committed homepage content from
`site.branch`. Uncommitted Markdown edits will not appear. There is no
live reload: commit content changes on that branch, stop with Ctrl-C and
run preview again. Name and tagline edits can be previewed without a
commit, but must be committed for production publication. If you work
through pull requests, preview against your topic branch by temporarily
setting `site.branch` to it; restore the production branch setting
before committing the manifest for merge.

## 4. Publish and verify

For a new site, continue with [first-site setup](GETTING_STARTED.md).
For an already configured site, push or merge the committed manifest and
homepage to the publishing branch and let its Partlet workflow finish.
For manual publication, use the configured R2 credentials and
`partlet publish --repo "$SOURCE_REPO"`.

After a successful run, check the public homepage and a project page.
Name and tagline changes update pages without changing exported history
or requiring new project approval. A homepage-only edit updates the
index, so project results can correctly say `unchanged`. Content edits
do not require a Worker deployment. Updating Partlet itself is a
separate task covered by [Upgrading Partlet](UPGRADING.md).

## Edit or remove the introduction

To edit it, change the selected Markdown, review it for private content,
commit on the publishing branch, preview, and publish again. To rename
the file, update `site.readme` and commit both changes together.

To remove it, remove or comment out `readme` in `[site]`, commit the
manifest and publish again. Do not use `readme = ""`, and do not delete
the file while the manifest still selects it. You can delete an unused
source file after removing the setting. Removing `tagline` restores an
empty footer tagline; removing `name` restores the hostname default.

`partlet unpublish` removes projects; it preserves the last published
site name, tagline and introduction. It is not a command for removing
homepage prose. After changing any of these settings, publish to make
the public change take effect.

## If a change does not appear

| Symptom | What to check |
| -- | -- |
| Preview shows old prose | Commit the Markdown on the configured local `site.branch`, then restart preview. |
| Missing-file or source-branch error | Check `--repo`, the source-root-relative path, and that the file exists as a regular file on the configured local branch. |
| Uncommitted-content error during publication | Commit the selected file and manifest; publish from the publishing branch tip. |
| Ambiguous-link error | Replace local relative paths with actual public URLs; Partlet will not upload their targets. |
| Public pages keep the old name or footer | Confirm the publishing workflow used the new manifest and updated Partlet version; inspect failed or skipped project results. |
| Homepage changed but project pages differ | A partial publication can update the index while failed projects retain their previous pages. Resolve those failures and republish. |
