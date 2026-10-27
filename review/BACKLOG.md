# Review backlog

Only work promoted from whole-codebase reviews belongs here. Every entry is ready for separate work and carries a `Findings:` line naming the raw review findings it covers; each finding maps to at most one entry. Claiming and resolving follow [docket/TODO_GUIDE.md](../docket/TODO_GUIDE.md); promotion follows [docket/CODE_REVIEW_GUIDE.md](../docket/CODE_REVIEW_GUIDE.md).

## P0 Critical

## P1 High

## P2 Normal

## P3 Low

## Unprioritized

- [SITE] `site-directory-key-layout` — **Make directory page keys representable by the local store.** A directory named `index.html` currently collides with its parent's page and fails publication.
  - Source: review/2026-10-24-0250-full.md, 2026-10-24
  - Starting point: `src/partlet/site/render.py:107`; coordinate the chosen layout with the future Worker route lookup.
  - Findings: `site-directory-index-key-collision`
  - Validation: publish an approved project containing `docs/index.html/leaf.txt` into a LocalStore; require success, distinct readable directory pages and a working clone.

- [TOOLING] `test-collection-git-isolation` — **Establish Git isolation before test modules are collected.** Import-time test code can still discover the enclosing checkout and original user configuration before the session fixture starts.
  - Source: review/2026-10-24-0250-full.md, 2026-10-24
  - Starting point: `tests/conftest.py:50` and `tests/conftest.py:94`; capture and arm the tripwire before entering isolation.
  - Findings: `collection-before-git-sandbox`
  - Validation: use a synthetic enclosing repository and original HOME; at module import, a read-only Git discovery probe must not find that repository and configuration must already be isolated. Keep existing sandbox/tripwire checks passing.
