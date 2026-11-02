"""One run at a time per source: a lock object created with a conditional put.

Every publish ends by sweeping keys that no pointer names, so a second run
against the same source could delete objects the first has uploaded but not
yet pointed at. The workflow's concurrency group serialises CI runs; this lock
also covers runs it cannot see (a local `partlet publish` or `unpublish`, or
another repository or workflow publishing the same source).
"""

from __future__ import annotations

import json
import os
import secrets
import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime

from partlet.store import Store


class LockError(Exception):
    """Another run holds the source's lock."""


def lock_key(source: str) -> str:
    return f"{source}/lock"


def describe_holder(environ: Mapping[str, str] = os.environ) -> str:
    """The GitHub Actions run URL in CI, otherwise host and process ID."""
    if environ.get("GITHUB_RUN_ID"):
        return (
            f"{environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{environ.get('GITHUB_REPOSITORY', '?')}/actions/runs/"
            f"{environ['GITHUB_RUN_ID']}"
        )
    return f"{socket.gethostname()} pid {os.getpid()}"


def read_lock(store: Store, source: str) -> dict | None:
    raw = store.get(lock_key(source))
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        return {"holder": "(unreadable lock)", "since": "?"}
    return value if isinstance(value, dict) else {"holder": "?", "since": "?"}


@contextmanager
def store_lock(store: Store, source: str, holder: str) -> Iterator[None]:
    token = secrets.token_hex(16)
    body = {
        "holder": holder,
        "since": datetime.now(UTC).isoformat(timespec="seconds"),
        "token": token,
    }
    data = (json.dumps(body, indent=2, sort_keys=True) + "\n").encode()
    created = store.put_if_absent(lock_key(source), data, "application/json")
    held = {} if created else read_lock(store, source) or {}
    # A client retry of a put whose first attempt succeeded, but whose
    # response was lost, finds the key present: the token says it is ours.
    if not created and held.get("token") != token:
        raise LockError(
            f"{source} is locked by {held.get('holder', '?')} since "
            f"{held.get('since', '?')}. If no publish is running (a killed job "
            "leaves its lock behind), remove it with: partlet unlock"
        )
    try:
        yield
    finally:
        # Release only our own lock: `partlet unlock` may have removed it and
        # another run taken it since. R2Store.delete makes one attempt only;
        # an uncertain response raises rather than retrying against a new lock.
        # R2 has no conditional delete: manually unlocking a live run can
        # still let another run acquire the key between this read and delete.
        if (read_lock(store, source) or {}).get("token") == token:
            store.delete(lock_key(source))
