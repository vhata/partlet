import json

import pytest

from partlet.lock import LockError, describe_holder, read_lock, store_lock
from partlet.store import LocalStore


def test_lock_is_exclusive_and_released(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "s", "first run"):
        held = json.loads(store.get("s/lock"))
        assert held["holder"] == "first run"
        with pytest.raises(LockError, match="locked by first run"):
            store_lock(store, "s", "second run").__enter__()
        assert read_lock(store, "s")["holder"] == "first run"
    assert store.get("s/lock") is None


def test_lock_is_released_when_the_body_fails(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(RuntimeError), store_lock(store, "s", "run"):
        raise RuntimeError("publish failed")
    assert store.get("s/lock") is None


def test_someone_elses_lock_is_left_alone(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "s", "first run"):
        # `partlet unlock`, then another run takes the lock.
        store.delete("s/lock")
        store.put_if_absent("s/lock", b'{"holder": "other", "token": "x"}')
    assert read_lock(store, "s")["holder"] == "other"


def test_a_retried_create_that_already_succeeded_still_holds_the_lock(tmp_path):
    class LostResponse(LocalStore):
        """The first conditional put lands, but its response is lost and the
        client's retry reports that the key exists."""

        def put_if_absent(self, key, data, content_type=None):
            super().put_if_absent(key, data, content_type)
            return False

    store = LostResponse(tmp_path)
    with store_lock(store, "s", "run"):
        assert read_lock(store, "s")["holder"] == "run"
    assert store.get("s/lock") is None


def test_lock_is_per_source(tmp_path):
    store = LocalStore(tmp_path)
    with store_lock(store, "a", "run"), store_lock(store, "b", "run"):
        assert store.get("a/lock") and store.get("b/lock")


def test_describe_holder():
    env = {
        "GITHUB_RUN_ID": "42",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "me/mono",
    }
    assert describe_holder(env) == "https://github.com/me/mono/actions/runs/42"
    assert " pid " in describe_holder({})


def test_lock_on_r2(r2_config):
    from partlet.store import R2Store

    store = R2Store(r2_config)
    with (
        store_lock(store, "s", "ci"),
        pytest.raises(LockError),
        store_lock(R2Store(r2_config), "s", "laptop"),
    ):
        raise AssertionError("acquired another holder's lock")
    assert store.get("s/lock") is None
