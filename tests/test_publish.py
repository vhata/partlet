import json

import pytest

from partlet.gitutil import git
from partlet.manifest import parse_manifest
from partlet.publish import build_id, publish_all
from partlet.store import LocalStore


def manifest(approved, extra="", description="Foo tool"):
    return parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
description = "{description}"
approved = "{approved}"
{extra}

[projects.unapproved]
path = "foo"
""")


def export_tip(mono, tmp_path):
    """The tip `partlet review` would show: export once and read it."""
    from partlet.export import export_project
    from partlet.manifest import Project

    dest = tmp_path / f"probe-{len(list(tmp_path.glob('probe-*')))}.git"
    return export_project(mono.path, "main", Project("foo", "foo"), dest)


def run(mono, tmp_path, store, approved, extra="", description="Foo tool"):
    work = tmp_path / f"work-{len(list(tmp_path.glob('work-*')))}"
    m = manifest(approved, extra, description)
    return {r.name: r for r in publish_all(mono.path, m, store, work)}


@pytest.fixture
def first(mono, tmp_path):
    mono.write("foo/README.md", "# Foo\n")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    store = LocalStore(tmp_path / "out")
    return store, approved


def test_first_publish_writes_everything(mono, tmp_path, first):
    store, approved = first
    results = run(mono, tmp_path, store, approved)
    assert results["foo"].status == "published"
    assert results["unapproved"].status == "skipped"

    current = json.loads(store.get("s/p/foo/current"))
    assert current["tip"] == approved
    assert current["build"] == build_id(approved, "Foo tool", "https://partlet.example")
    assert current["description"] == "Foo tool"
    build = current["build"]
    assert store.get(f"s/p/foo/site/{build}/index.html") is not None
    assert store.get(f"s/p/foo/site/{build}/raw/a.txt") == b"one\n"
    assert store.get(f"s/p/foo/archive/{approved}.tar.gz") is not None
    assert store.get(f"s/p/foo/archive/{approved}.zip") is not None
    assert (
        store.get("s/p/foo/git/info/refs") == f"{approved}\trefs/heads/main\n".encode()
    )

    index = json.loads(store.get("s/index.json"))
    assert [p["name"] for p in index] == ["foo"]
    assert b'href="/foo"' in store.get("s/index.html")
    assert b".hl" in store.get("s/static/style.css")


def test_second_run_without_changes_is_unchanged(mono, tmp_path, first, serve):
    store, approved = first
    run(mono, tmp_path, store, approved)
    packs_before = store.list("s/p/foo/git/objects/pack/")
    results = run(mono, tmp_path, store, approved)
    assert results["foo"].status == "unchanged"
    assert store.list("s/p/foo/git/objects/pack/") == packs_before
    with serve(tmp_path / "out") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "a.txt").read_text() == "one\n"


def test_new_commits_publish_and_old_build_is_cleaned_up_one_publish_later(
    mono, tmp_path, first
):
    store, approved = first
    run(mono, tmp_path, store, approved)
    build1 = json.loads(store.get("s/p/foo/current"))["build"]

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    assert run(mono, tmp_path, store, approved)["foo"].status == "published"
    build2 = json.loads(store.get("s/p/foo/current"))["build"]
    assert build2 != build1
    assert store.list(f"s/p/foo/site/{build1}/")  # still present: one publish of grace
    assert f"s/p/foo/site/{build1}/index.html" in json.loads(
        store.get("s/p/foo/cleanup.json")
    )

    mono.write("foo/a.txt", "one\ntwo\nthree\n")
    mono.commit("c3")
    run(mono, tmp_path, store, approved)
    assert store.list(f"s/p/foo/site/{build1}/") == []
    assert store.list(f"s/p/foo/site/{build2}/")


def test_description_change_rerenders_without_new_pack(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    packs = store.list("s/p/foo/git/objects/pack/")
    changed = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"
[projects.foo]
path = "foo"
description = "New words"
approved = "{approved}"
""")
    results = {
        r.name: r for r in publish_all(mono.path, changed, store, tmp_path / "w-desc")
    }
    assert results["foo"].status == "published"
    assert store.list("s/p/foo/git/objects/pack/") == packs
    assert json.loads(store.get("s/p/foo/current"))["description"] == "New words"


def test_rewrite_is_rejected_and_nothing_changes(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    before = store.get("s/p/foo/git/info/refs")
    git(
        "commit",
        "-q",
        "--amend",
        "-m",
        "rewritten",
        cwd=mono.path,
        env={
            "GIT_COMMITTER_DATE": "1767229200 +0000",
            "GIT_AUTHOR_DATE": "1767229200 +0000",
        },
    )
    new_approved = export_tip(mono, tmp_path)
    result = run(mono, tmp_path, store, new_approved)["foo"]
    assert result.status == "failed" and "rewrite" in result.reason
    assert store.get("s/p/foo/git/info/refs") == before


def test_allowed_rewrite_publishes_full_pack(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    old_tip = approved
    git(
        "commit",
        "-q",
        "--amend",
        "-m",
        "rewritten",
        cwd=mono.path,
        env={
            "GIT_COMMITTER_DATE": "1767229200 +0000",
            "GIT_AUTHOR_DATE": "1767229200 +0000",
        },
    )
    new_tip = export_tip(mono, tmp_path)
    result = run(
        mono, tmp_path, store, new_tip, extra=f'allow_rewrite_of = "{old_tip}"'
    )["foo"]
    assert result.status == "published"
    packs = store.get("s/p/foo/git/objects/info/packs").decode().split()
    assert packs.count("P") == 1


def test_missing_directory_fails_project_but_index_still_written(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    mono.mv("foo", "bar")
    mono.commit("move without manifest update")
    result = run(mono, tmp_path, store, approved)["foo"]
    assert result.status == "failed" and "previous_paths" in result.reason
    assert store.get("s/index.json") is not None
    assert json.loads(store.get("s/p/foo/current"))["tip"] == approved


def test_base_url_change_rerenders_without_new_pack(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    packs = store.list("s/p/foo/git/objects/pack/")
    build_before = json.loads(store.get("s/p/foo/current"))["build"]
    changed = parse_manifest(f"""
[site]
source = "s"
base_url = "https://other.example"
[projects.foo]
path = "foo"
description = "Foo tool"
approved = "{approved}"
""")
    results = {
        r.name: r for r in publish_all(mono.path, changed, store, tmp_path / "w-url")
    }
    assert results["foo"].status == "published"
    assert store.list("s/p/foo/git/objects/pack/") == packs
    current = json.loads(store.get("s/p/foo/current"))
    assert current["build"] != build_before
    assert current["build"] == build_id(approved, "Foo tool", "https://other.example")


def test_unexpected_error_fails_only_that_project_and_index_is_written(mono, tmp_path):
    from partlet.export import export_project
    from partlet.manifest import Project

    mono.write("foo/a.txt", "one\n")
    mono.write("bar/b.txt", "two\n")
    mono.commit("c1")
    tips = {
        name: export_project(
            mono.path, "main", Project(name, name), tmp_path / f"probe-{name}.git"
        )
        for name in ("foo", "bar")
    }
    both = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"
[projects.foo]
path = "foo"
approved = "{tips["foo"]}"
[projects.bar]
path = "bar"
approved = "{tips["bar"]}"
""")
    store = LocalStore(tmp_path / "out")
    publish_all(mono.path, both, store, tmp_path / "w-0")

    store.put("s/p/foo/current", b"not json")
    mono.write("bar/b.txt", "two\nmore\n")
    mono.commit("c2")
    tips["bar"] = export_project(
        mono.path, "main", Project("bar", "bar"), tmp_path / "probe-bar-2.git"
    )
    both = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"
[projects.foo]
path = "foo"
approved = "{tips["foo"]}"
[projects.bar]
path = "bar"
approved = "{tips["bar"]}"
""")
    results = {r.name: r for r in publish_all(mono.path, both, store, tmp_path / "w-1")}
    assert results["foo"].status == "failed"
    assert "JSONDecodeError" in results["foo"].reason
    assert results["bar"].status == "published"
    index = json.loads(store.get("s/index.json"))
    assert [p["name"] for p in index] == ["bar"]


class InterruptedStore(LocalStore):
    """Fails the put of one key, as if the publish died at that point."""

    def __init__(self, root, fail_key):
        super().__init__(root)
        self.fail_key = fail_key

    def put(self, key, data, content_type=None):
        if key == self.fail_key:
            raise OSError(f"interrupted before {key}")
        super().put(key, data, content_type)


class RecordingStore(LocalStore):
    """Records each deleted key with the build `current` named at that moment."""

    def __init__(self, root):
        super().__init__(root)
        self.deleted = []

    def delete(self, key):
        build = json.loads(self.get("s/p/foo/current"))["build"]
        self.deleted.append((key, build))
        super().delete(key)


def test_stale_cleanup_list_never_deletes_the_live_build(mono, tmp_path, first, serve):
    store, approved = first
    out = tmp_path / "out"
    run(mono, tmp_path, store, approved, description="X")
    build_x = json.loads(store.get("s/p/foo/current"))["build"]
    run(mono, tmp_path, store, approved, description="Y")

    # Back to X: the same build ID again, interrupted after `current` moves
    # but before `cleanup.json`, which still lists the X build as dead.
    interrupted = InterruptedStore(out, "s/p/foo/cleanup.json")
    result = run(mono, tmp_path, interrupted, approved, description="X")["foo"]
    assert result.status == "failed"
    assert json.loads(store.get("s/p/foo/current"))["build"] == build_x
    assert f"s/p/foo/site/{build_x}/index.html" in json.loads(
        store.get("s/p/foo/cleanup.json")
    )

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    recording = RecordingStore(out)
    result = run(mono, tmp_path, recording, approved, description="X")["foo"]
    assert result.status == "published"
    live = [key for key, build in recording.deleted if f"/site/{build}/" in key]
    assert live == []
    build = json.loads(store.get("s/p/foo/current"))["build"]
    assert store.get(f"s/p/foo/site/{build}/index.html") is not None
    with serve(out) as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "a.txt").read_text() == "one\ntwo\n"
