# Deferred work

Ordinary follow-ups and bugs found during other work live here. Whole-codebase review findings promoted for separate work live in [review/BACKLOG.md](review/BACKLOG.md). Follow [docket/TODO_GUIDE.md](docket/TODO_GUIDE.md) before adding, claiming, moving or resolving an entry. Entries in **Ready for separate work** are unblocked and available now; an understood entry with an unresolved `Depends on:` or a `Blocked by:` goes in **Waiting** until it clears.

## Needs triage

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

## Needs proof of concept

### P0 Critical

### P1 High

### P2 Normal

### P3 Low

### Unprioritized

- [WORKER] `macos-http2-default-clone` — **Restore plain clone and incremental pull for the macOS client that hangs over HTTP/2.** The first hosted synthetic trial needs a per-clone HTTP/1.1 workaround, leaving the no-client-configuration quality requirement unmet for this client.
  - Source: user-reported first hosted trial, task/macos-http2-compatibility, 2026-11-03
  - Starting point: [macOS clone troubleshooting](docs/PUBLISHING.md#macos-clone-hangs-over-http2), `worker/src/index.ts` Git responses and `worker/src/route.ts` missing-object probes.
  - Evidence: Homebrew Git 2.56.0 links Apple's libcurl 8.7.1; expected 404 probes precede header corruption and a stalled clone. System curl 8.7.1 reproduces HTTP/2 errors with `--fail`; curl 8.23.0 handles the same sequence correctly. HTTP/1.1 clone and an unchanged pull pass. A process-local dynamic-loader override made the same Git load libcurl 8.23.0 and pass HTTP/2 clone plus a hosted incremental pull from `6e3b500` to `12ac7da` without HTTP-version settings; normal Git installation remains unchanged.
  - Investigation: determine a durable Git/libcurl client repair or a proportionate server mitigation preserving dumb-HTTP semantics, correct missing-object responses, read-only serving and Worker resource limits. Cloudflare deployment/settings experiments remain user-run.
  - Acceptance: reproduce the affected client's default-protocol failure, then verify plain clone and a pull after a second hosted publication without per-command, per-repository or global HTTP-version settings or diagnostic loader overrides. Record client/runtime-library versions and distinguish a verified durable client repair from a Partlet-side fix. Keep the gap open until that evidence exists.

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
