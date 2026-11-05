# Site themes

Status: accepted design. See [Site themes](../THEMES.md) for usage and
the theme-author contract.

Partlet should let a publisher choose a bundled theme, adjust its
appearance, or use a third-party theme without forking Partlet. Theme
selection belongs in the source repository so local builds and the
GitHub Action produce the same site.

## Publisher experience

Site configuration:

```toml
[site.theme]
name = "paper"
mode = "auto"
```

Ship three distinct bundled themes:

| Theme | Direction |
| -- | -- |
| `classic` | Preserve today's compact repository browser. |
| `paper` | A spacious, reading-oriented presentation with serif prose. |
| `terminal` | A restrained monospace presentation with strong code emphasis. |

Each supports `auto`, `light`, and `dark`. Auto follows the browser's
color preference using CSS; a visitor preference switch is outside this
first version. Omitting the theme selects Classic in auto mode and
preserves existing manifests. One theme covers the entire site: project
index, directory listings, README content, file views and code colors.
Per-project themes are deferred.

For a third-party theme, copy its distribution into the source
repository and select its directory:

```toml
[site.theme]
path = "themes/my-theme"
mode = "auto"
```

`name` and `path` are mutually exclusive. Invalid names, unsupported
formats, missing files and invalid options fail before publication with
an actionable message; never silently substitute another theme.

The `partlet theme list` and `partlet theme check` commands expose
bundled choices and validate the configured theme locally. Documentation
must provide a complete example and screenshots of each bundled theme.

## Theme contract

Partlet owns semantic HTML, page data, links and escaping. Themes
control presentation through documented CSS variables and stable CSS
hooks for headers, navigation, listings, README content, code and line
numbers. Expose colors, typography, spacing, content width, borders and
focus states. Theme CSS loads after structural and syntax-highlighting
CSS so its documented overrides take effect. Syntax colors must work in
both light and dark modes rather than retaining Pygments' current
default palette against a dark background.

A third-party distribution contains:

```text
my-theme/
  theme.toml
  style.css
  LICENSE
  assets/       # optional raster images
```

The versioned `theme.toml` contract declares a stable ID, display name,
theme version, format version, supported modes, license and explicit
public asset list. Version 1 requires all three modes. Only the declared
stylesheet and raster assets are published; metadata and license remain
available locally. Keep credits and provenance in the distribution.
Unknown format versions fail clearly. Document compatible CSS hooks as
part of the theme format and change that version when breaking them.

Themes do not provide Python entry points, build hooks, JavaScript or
Jinja templates. Version 1 uses system fonts and PNG, JPEG, GIF or WebP
images; custom fonts, SVG and layout templates need separate designs.
Theme CSS is trusted publisher-supplied presentation code: it can
obscure content or cause network requests. Disabling scripts does not
make an arbitrary theme safe. The owner reviews its CSS and declared
public assets before committing it. Existing README image behavior and
the Worker's script restrictions remain in force; do not promise
complete network isolation under the current image CSP.

Installation initially means vendoring a reviewed distribution and
committing it with its license and origin/revision recorded. It needs no
package registry, pip dependency, marketplace, credentials or runtime
download. An optional download/install convenience command can follow
later with its own immutable-source and integrity design.

## Build and publication

Current integration points are `src/partlet/manifest.py`,
`src/partlet/site/render.py`, `src/partlet/site/highlight.py`,
`src/partlet/site/style.css`, `src/partlet/publish.py`, and the Worker's
asset routes. The current renderer loads package-owned Jinja templates;
every page references mutable `/_partlet/style.css`. The Worker also
generates its own 404 page with that URL.

Resolve a theme once per operation and pass an immutable resolved object
through rendering and publication. Read vendored inputs from the
configured publishing commit, relative to the manifest directory, with
the same committed-input consistency guarantees as the manifest. Local
builds must also use an explicit, documented input revision. Reject
absolute paths, traversal, symlinks and undeclared files; theme
selection cannot expose arbitrary private checkout contents. Theme
assets are additional public content outside exported project history
and must be identified as such in the publishing guide.

Hash the resolved format, relevant options, structural CSS, syntax CSS,
theme CSS and declared asset names/bytes. Include that fingerprint in
project build identity. A theme-only edit must rebuild pages even when
the exported Git tip has not changed, without changing public Git
history, archives or approval semantics. Snapshot the inputs before any
write so one operation cannot mix theme versions.

Serve immutable resources from a reserved namespace such as
`/_partlet/themes/<digest>/style.css` and
`/_partlet/themes/<digest>/assets/<name>`. Write resources before pages,
index updates or live pointers that reference them. Resource URLs inside
CSS must resolve within that digest's asset directory. Keep the legacy
stylesheet route for old pages and the Worker-generated fallback 404;
the 404 deliberately retains Classic styling in version 1.

Worker routes must validate the digest and allowed asset path, use an
explicit MIME allowlist and preserve security headers. Never turn the
namespace into arbitrary bucket-key access. Do not expand script or font
permissions to support version 1.

Retain immutable theme resources in version 1 rather than deleting them
on a theme switch. This protects cached pages and current/previous
builds of projects that were skipped or failed to publish. Document the
small accumulating storage cost; future garbage collection needs
reference and cache-lifetime proof. Preserve current site theme metadata
in the store so unpublish can regenerate the index without local theme
source files or changing surviving projects' presentation. Existing
deployments with no metadata use the legacy default.

Bundled theme data must be present in installed wheels and source
distributions, not just a development checkout. The installed CLI and
Action must resolve identical assets without network access.

## Delivery and acceptance

1. Implement bundled themes, the stable styling contract, mode
   selection, fingerprinted publication and narrow Worker CSS routes.
   Test using the installed package and keep the default visually
   compatible.
1. Build on that contract to add vendored third-party packs and their
   static asset routes. Include a small example distribution and a
   theme-author guide showing how to install and adapt it.

Both stages require meaningful render, manifest, publication and Worker
checks. Cover theme-only changes on unchanged Git history, invalid
inputs before writes, repeated builds, interrupted publication,
missing/skipped projects, unpublish, legacy pages, and package contents.
Third-party checks additionally cover asset allowlists, escaping paths,
symlinks, committed-input consistency and unsupported format versions.

For each bundled theme, manually inspect the index, nested tree, README,
highlighted source, long names, narrow screens and keyboard focus in
both light and dark modes. Record screenshots and contrast evidence.
Static tests and local simulated R2 checks do not establish browser
appearance or hosted behavior. No cloud provisioning or deployment is
part of this design work.
