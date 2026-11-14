# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [TOOLING] `publisher-credential-bootstrap` — **Design optional API creation of bucket-scoped publisher credentials and transfer to GitHub secrets.** Cloudflare supports token creation through its API, but requires a separate dashboard-created bootstrap token with token-management permission; decide whether the benefit for repeated installations justifies that authority and recovery complexity.
  - Source: Cloudflare setup automation request, branch vhata/cloudflare-dashboard-automation, 2026-11-05
  - Starting point: docs/GETTING_STARTED.md credential step; https://developers.cloudflare.com/r2/api/tokens/ and https://developers.cloudflare.com/fundamentals/api/how-to/create-via-api/. Keep the bootstrap token out of files and logs; scope generated credentials to one bucket, transfer secrets over stdin, and define recovery for unknown token-creation or partial GitHub-secret updates before implementation.

## Needs proof of concept

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Waiting

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Ready for separate work

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized
