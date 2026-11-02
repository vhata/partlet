"""Pack retirement is timed, persistent and safe across publication retries."""

import json

import pytest
from helpers import export_tip

from partlet import gitstatic, publish
from partlet.gitutil import git
from partlet.manifest import parse_manifest
from partlet.publish import PACK_RETENTION_SECONDS, _sweep_packs
from partlet.store import LocalStore, StoreError

PREFIX = "s/p/foo"
PACK = f"{PREFIX}/git/objects/pack/pack-{'a' * 40}.pack"
INDEX = PACK.removesuffix("pack") + "idx"
STATE = f"{PREFIX}/retired-packs.json"


def test_retirement_uses_first_observed_time_and_unchanged_sweeps_expire(
    tmp_path, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(publish.time, "time", lambda: clock[0])
    store = LocalStore(tmp_path)
    for key in (PACK, INDEX):
        store.put(key, b"orphaned or formerly advertised object")
    _sweep_packs(store, PREFIX, set())
    initial = store.get(STATE)
    clock[0] += PACK_RETENTION_SECONDS - 1
    _sweep_packs(LocalStore(tmp_path), PREFIX, set())
    assert store.get(STATE) == initial  # a fresh process does not renew grace
    assert store.get(PACK) is not None
    assert store.get(INDEX) is not None
    clock[0] += 1
    _sweep_packs(LocalStore(tmp_path), PREFIX, set())
    assert store.get(PACK) is None
    assert store.get(INDEX) is None
    _sweep_packs(store, PREFIX, set())
    assert json.loads(store.get(STATE)) == {}


def test_revived_pack_gets_a_new_window_and_clock_rollback_never_expires(
    tmp_path, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(publish.time, "time", lambda: clock[0])
    store = LocalStore(tmp_path)
    store.put(PACK, b"pack")
    _sweep_packs(store, PREFIX, set())
    clock[0] += PACK_RETENTION_SECONDS
    _sweep_packs(store, PREFIX, {PACK})
    assert store.get(PACK) == b"pack"
    assert json.loads(store.get(STATE)) == {}
    _sweep_packs(store, PREFIX, set())
    assert json.loads(store.get(STATE))[PACK] == clock[0]
    clock[0] = 0
    _sweep_packs(store, PREFIX, set())
    assert store.get(PACK) == b"pack"


@pytest.mark.parametrize("state", [b"{", b"[]", b'{"pack": true}', b'{"pack": NaN}'])
def test_invalid_retirement_state_fails_closed(tmp_path, state):
    store = LocalStore(tmp_path)
    store.put(PACK, b"pack")
    store.put(STATE, state)
    with pytest.raises(StoreError, match="invalid pack retirement state"):
        _sweep_packs(store, PREFIX, set())
    assert store.get(PACK) == b"pack"


def test_retirement_write_failure_cannot_delete_any_pack(tmp_path, monkeypatch):
    class FailingStore(LocalStore):
        def put(self, key, data, content_type=None):
            if key == STATE:
                raise StoreError("interrupted retirement write")
            super().put(key, data, content_type)

    store = FailingStore(tmp_path)
    store.put(PACK, b"pack")
    with pytest.raises(StoreError, match="interrupted retirement"):
        _sweep_packs(store, PREFIX, set())
    assert store.get(PACK) == b"pack"


def test_failed_expiry_delete_reuses_persisted_timer(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(publish.time, "time", lambda: clock[0])

    class DeleteFailure(LocalStore):
        def delete(self, key):
            raise StoreError("uncertain deletion")

    store = LocalStore(tmp_path)
    store.put(PACK, b"pack")
    _sweep_packs(store, PREFIX, set())
    clock[0] += PACK_RETENTION_SECONDS
    with pytest.raises(StoreError, match="uncertain deletion"):
        _sweep_packs(DeleteFailure(tmp_path), PREFIX, set())
    assert json.loads(store.get(STATE))[PACK] == 1000
    _sweep_packs(store, PREFIX, set())
    assert store.get(PACK) is None


def test_republished_pack_loses_old_timer_before_pointer_failure(
    mono, tmp_path, monkeypatch
):
    clock = [1000.0]
    monkeypatch.setattr(publish.time, "time", lambda: clock[0])
    monkeypatch.setattr(gitstatic, "MAX_PACKS", 1)
    mono.write("foo/a.txt", "first\n")
    original = mono.commit("first source")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "store")

    def run(store, rewrite=""):
        manifest = parse_manifest(
            '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n'
            f'\n[projects.foo]\npath = "foo"\napproved = "{approved}"\n{rewrite}'
        )
        work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
        return publish.publish_all(mono.path, manifest, store, work)[0]

    assert run(store).status == "published"
    initial_packs = store.list(f"{PREFIX}/git/objects/pack/")
    for generation in (2, 3):
        mono.write("foo/a.txt", f"update {generation}\n")
        mono.commit(f"update {generation}")
        assert run(store).status == "published"
    retired = json.loads(store.get(STATE))
    assert set(initial_packs) <= retired.keys()
    published_tip = json.loads(store.get(f"{PREFIX}/current"))["tip"]
    clock[0] += PACK_RETENTION_SECONDS + 1
    git("reset", "--hard", original, cwd=mono.path)

    class FailAfterCurrent(LocalStore):
        def put(self, key, data, content_type=None):
            super().put(key, data, content_type)
            if key == f"{PREFIX}/current":
                raise StoreError("interrupted after pointers moved")

    failed = run(
        FailAfterCurrent(store.root), f'allow_rewrite_of = "{published_tip}"\n'
    )
    assert failed.status == "failed"
    assert json.loads(store.get(f"{PREFIX}/current"))["tip"] == approved
    assert not set(initial_packs) & json.loads(store.get(STATE)).keys()
    for key in initial_packs:
        assert store.get(key) is not None
