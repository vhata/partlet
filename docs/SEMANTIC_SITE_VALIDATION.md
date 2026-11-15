# Semantic site validation

The output-version-1 renderer and format-2 themes were exercised with a
synthetic project on 2026-11-12. This records local evidence, not hosted
Cloudflare behavior or private repository acceptance.

## Browser matrix

Headless Chromium 153.0.8010.12 rendered Classic, Paper, Terminal and
the committed Copper example, each in explicit light and dark modes at
390 × 1000 and 1440 × 1000 viewports. JavaScript was disabled
throughout. The 144 page checks covered the index, root, two nested
directories, source, a long unusual filename, symlink, binary and
oversized-file pages. Fixtures included both Markdown and plaintext
READMEs.

Each page was checked for horizontal page overflow and keyboard focus on
the skip link. README source links were clicked; source line 2 anchors
were followed and the scrolling source region was focused. Stylesheets
were removed to check the unstyled root's headings, listing headers and
README link. Screenshot inspection covered each theme, both colors and
both widths. The narrow Terminal kind column was widened after this
inspection; long names wrap without hiding their characters.

Requests were fulfilled directly from renderer-produced HTML/CSS maps in
the browser harness. This isolates presentation evidence from Worker
routing and network behavior. It is not a screen-reader audit, a formal
contrast audit, or cross-browser acceptance. Automatic color preference
uses the existing CSS media-query contract; the matrix selected explicit
light/dark modes.

Representative captures:

- [Classic desktop](images/semantic/classic-desktop.png)
- [Paper dark narrow](images/semantic/paper-narrow.png)
- [Terminal unusual names](images/semantic/terminal-names.png)
- [Copper source and line anchors](images/semantic/copper-source.png)
- [Unstyled root](images/semantic/unstyled.png)

## Automated contract and integration evidence

`tests/test_semantic_html.py` parses all page and content kinds and
asserts complete revisions, exact timezone timestamps, original paths,
entry kinds, raw byte counts, table headers and landmarks. It includes
escaping, unusual names, Markdown/plaintext README rendering, symlinks,
binary and oversized content. `tests/test_page_models.py` additionally
checks timestamp rejection, exported provenance and source-free removal.

`tests/test_publish_themes.py` exercises renderer-only regeneration with
unchanged exported history and approval pins, format-1 rejection before
store writes, incompatible durable-presentation rejection before
removal, and failures at resource, presentation and index writes. Older
live pages keep their referenced immutable resources when projects fail
or are skipped. The publication interruption suite covers failure at
every storage operation and recovery.

`tests/test_preview.py` checks the same version and exported revision in
unapproved preview output, raw bytes and cloneable Git history. A wheel
built from the source distribution rendered the same eight theme/mode
fixture maps byte-for-byte as the checkout, including packaged templates
and CSS. The old separate stylesheet is absent from the package inputs.

The local harness, full matrix screenshots, JSON report and package
parity script are retained under `.docket/semantic-browser/` in the
implementation worktree. The focused renderer/theme/preview run passed
124 tests. The final `bash scripts/check.sh` passed 731 Python tests,
305 Worker tests, formatting/lint/type checks, the bundle dry run and
local Worker clone/pull smoke. `bash scripts/e2e.sh` passed all three
CLI-to-Worker scenarios. Queue, link and PR-marker checks also passed.

Local Node checks used the available 24.19.0 runtime; the repository
pins 24.22.0, which was not found locally. Setup used the available npm
11.20.0. No global tool or repository pin was changed.

## Site identity and optional homepage

The identity/homepage change was checked with synthetic long names,
taglines and Markdown prose across Classic, Paper, Terminal and Copper,
explicit light/dark modes, 390/1440-pixel widths and intro on/off. All
32 headless Chromium checks passed without horizontal page overflow.
Each checked keyboard focus on the skip link followed by the home header
link. JavaScript was disabled. Requests were fulfilled from renderer
maps with no server or external requests. Screenshots and the
reproducible harness are retained in `.docket/identity-browser/` in the
implementation worktree. A representative narrow Paper screenshot was
visually inspected. The wheel built through the source distribution
produced byte-identical fixture maps. This is local presentation/package
evidence, not hosted, private-data, cross-browser, contrast or
screen-reader acceptance.
