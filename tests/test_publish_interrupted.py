"""A publish that dies at any single write or delete never breaks what is live."""

import json
import shutil

from helpers import export_tip

from partlet.archive import ARCHIVE_FORMATS
from partlet.gitstatic import read_state
from partlet.gitutil import git, git_out
from partlet.manifest import parse_manifest
from partlet.publish import publish_all
from partlet.r2 import StoreError
from partlet.store import LocalStore


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


def manifest(approved):
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""")


def publish(mono, tmp_path, store, approved):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    try:
        (result,) = publish_all(mono.path, manifest(approved), store, work)
    except StoreError:
        return None  # the failure hit the site index, after the project
    return result


def assert_live_state_complete(store):
    """Every key the live pointers name exists."""
    prefix = "s/p/foo"
    for pack in read_state(store, f"{prefix}/git").packs:
        for ext in ("pack", "idx"):
            assert store.get(f"{prefix}/git/objects/pack/{pack}.{ext}") is not None
    current = json.loads(store.get(f"{prefix}/current"))
    assert store.get(f"{prefix}/site/{current['build']}/index.html") is not None
    for fmt in ARCHIVE_FORMATS:
        assert store.get(f"{prefix}/archive/{current['tip']}.{fmt}") is not None


def test_failure_at_every_operation_leaves_a_cloneable_repo_and_a_retry_recovers(
    mono, tmp_path, serve
):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    base = tmp_path / "base"
    store = LocalStore(base)
    for n in (2, 3):  # two earlier publishes, so the sweep has keys to delete
        assert publish(mono, tmp_path, store, approved).status == "published"
        mono.write("foo/README.md", f"# Foo {n}\n")
        mono.commit(f"c{n}")
    old_tip = read_state(store, "s/p/foo/git").tip
    new_tip = export_tip(mono, tmp_path)

    counting = FlakyStore(tmp_path / "count")
    shutil.copytree(base, counting.root)
    assert publish(mono, tmp_path, counting, approved).status == "published"
    assert counting.ops > 10

    for fail_at in range(1, counting.ops + 1):
        root = tmp_path / f"case-{fail_at}"
        shutil.copytree(base, root)
        failed = publish(mono, tmp_path, FlakyStore(root, fail_at), approved)
        # None: the failure hit the site index, after the project finished.
        assert failed is None or failed.status == "failed", (fail_at, failed)
        after_failure = LocalStore(root)
        assert_live_state_complete(after_failure)
        clone = tmp_path / f"clone-{fail_at}"
        with serve(root) as url:
            git("clone", "-q", f"{url}/s/p/foo/git", str(clone), cwd=tmp_path)
        assert git_out("rev-parse", "HEAD", cwd=clone) in (old_tip, new_tip)

        retry = publish(mono, tmp_path, after_failure, approved)
        assert retry.status in ("published", "unchanged"), (fail_at, retry)
        assert_live_state_complete(after_failure)
        assert read_state(after_failure, "s/p/foo/git").tip == new_tip
        index = json.loads(after_failure.get("s/index.json"))
        assert [(p["name"], p["tip"]) for p in index] == [("foo", new_tip)]
        with serve(root) as url:
            git("pull", "-q", "--ff-only", f"{url}/s/p/foo/git", "main", cwd=clone)
        assert git_out("rev-parse", "HEAD", cwd=clone) == new_tip
