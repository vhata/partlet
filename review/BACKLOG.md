# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [PUBLISHER] `publish-retry-static-head` — **Restore Git HEAD.** A successful retry of an interrupted first publication currently leaves the metadata endpoint missing until the export tip advances.

  - Source: review/2026-11-03-1933-full.md, 2026-11-03
  - Starting point: `publish_project` in `src/partlet/publish.py` and `write_pointers` in `src/partlet/gitstatic.py`; interrupt before the first HEAD write, then retry without advancing history.
  - Findings: `publish-retry-missing-head`

- [PUBLISHER] `export-colon-path-validation` — **Handle colon paths.** Support colon-containing project paths or reject them before export. Manifest normalization accepts paths that filter-repo's path-rename syntax cannot use.

  - Source: review/2026-11-03-1933-full.md, 2026-11-03
  - Starting point: `normalize_path` in `src/partlet/manifest.py` and `export_project` in `src/partlet/export.py`; reproduce with `foo:bar`.
  - Findings: `export-colon-path-rename`
