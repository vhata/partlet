"""A publish that dies at any single write or delete never breaks what is live."""

import json
import shutil

import pytest
from helpers import export_tip

from partlet import gitstatic
from partlet.archive import ARCHIVE_FORMATS
from partlet.gitstatic import read_state
from partlet.gitutil import git, git_out
from partlet.manifest import parse_manifest
from partlet.publish import publish_all
from partlet.store import LocalStore, StoreError


class FlakyStore(LocalStore):
    """Counts puts and deletes, and fails operation number `fail_at` (from 1)."""

    def __init__(self, root, fail_at=None):
        super().__init__(root)
        self.fail_at = fail_at
        self.ops = 0

    def _tick(self, what):
        self.ops += 1
        if self.ops == self.fail_at:
            raise StoreError(f"injected failure at operation {self.ops}: {what}")

    def put(self, key, data, content_type=None):
        self._tick(f"put {key}")
        super().put(key, data, content_type)

    def delete(self, key):
        self._tick(f"delete {key}")
        super().delete(key)


def manifest(approved, rewrite_of=None):
    rewrite = f'allow_rewrite_of = "{rewrite_of}"' if rewrite_of else ""
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
{rewrite}
""")


def publish(mono, tmp_path, store, approved, rewrite_of=None):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    try:
        (result,) = publish_all(mono.path, manifest(approved, rewrite_of), store, work)
    except StoreError:
        return None  # the failure hit the site index, after the project
    return result


def assert_live_state_complete(store):
    """Every key the live pointers name exists."""
    prefix = "s/p/foo"
    for pack in read_state(store, f"{prefix}/git").packs:
        for ext in ("pack", "idx"):
            assert store.get(f"{prefix}/git/objects/pack/{pack}.{ext}") is not None
    raw = store.get(f"{prefix}/current")
    if raw is None:
        return  # a first publication has not made a site live yet
    current = json.loads(raw)
    assert store.get(f"{prefix}/site/{current['build']}/index.html") is not None
    for fmt in ARCHIVE_FORMATS:
        assert store.get(f"{prefix}/archive/{current['tip']}.{fmt}") is not None


@pytest.mark.parametrize("scenario", ["first", "incremental", "rewrite", "consolidate"])
def test_failure_at_every_operation_leaves_a_cloneable_repo_and_a_retry_recovers(
    mono, tmp_path, serve, monkeypatch, scenario
):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    base = tmp_path / "base"
    base.mkdir()
    store = LocalStore(base)
    if scenario != "first":
        for n in (2, 3):  # establish both a live generation and cleanup candidates
            assert publish(mono, tmp_path, store, approved).status == "published"
            mono.write("foo/README.md", f"# Foo {n}\n")
            mono.commit(f"c{n}")
    old_tip = read_state(store, "s/p/foo/git").tip
    rewrite_of = None
    if scenario == "rewrite":
        git("checkout", "-q", "--orphan", "replacement", cwd=mono.path)
        mono.write("foo/README.md", "# Replaced history\n")
        mono.commit("replacement root")
        git("branch", "-q", "-M", "main", cwd=mono.path)
        approved = export_tip(mono, tmp_path)
        rewrite_of = old_tip
    elif scenario == "consolidate":
        monkeypatch.setattr(gitstatic, "MAX_PACKS", 2)
    new_tip = export_tip(mono, tmp_path)

    counting = FlakyStore(tmp_path / "count")
    shutil.copytree(base, counting.root)
    assert publish(mono, tmp_path, counting, approved, rewrite_of).status == "published"
    assert counting.ops > 10

    # One loopback server serves disjoint fixtures for the entire exhaustive
    # run. Every injected operation still gets an actual Git clone and fetch.
    with serve(tmp_path) as url:
        for fail_at in range(1, counting.ops + 1):
            root = tmp_path / f"case-{fail_at}"
            shutil.copytree(base, root)
            failed = publish(
                mono, tmp_path, FlakyStore(root, fail_at), approved, rewrite_of
            )
            assert failed is None or failed.status == "failed", (fail_at, failed)
            after_failure = LocalStore(root)
            assert_live_state_complete(after_failure)
            clone = tmp_path / f"clone-{fail_at}"
            remote = f"{url}/case-{fail_at}/s/p/foo/git"
            if after_failure.get("s/p/foo/current") is not None:
                git("clone", "-q", remote, str(clone), cwd=tmp_path)
                assert git_out("rev-parse", "HEAD", cwd=clone) in (old_tip, new_tip)

            retry = publish(mono, tmp_path, after_failure, approved, rewrite_of)
            assert retry.status in ("published", "unchanged"), (fail_at, retry)
            assert_live_state_complete(after_failure)
            assert read_state(after_failure, "s/p/foo/git").tip == new_tip
            index = json.loads(after_failure.get("s/index.json"))
            assert [(p["name"], p["tip"]) for p in index] == [("foo", new_tip)]
            if not clone.exists():
                git("clone", "-q", remote, str(clone), cwd=tmp_path)
            elif scenario == "rewrite":
                # Rewrites intentionally require an explicit client reset.
                git("fetch", "-q", remote, "main", cwd=clone)
                git("reset", "--hard", "FETCH_HEAD", cwd=clone)
            else:
                git("pull", "-q", "--ff-only", remote, "main", cwd=clone)
            assert git_out("rev-parse", "HEAD", cwd=clone) == new_tip
