import json

import pytest

from partlet import gitstatic
from partlet.archive import ARCHIVE_FORMATS
from partlet.gitstatic import PACK_EXTS, read_state
from partlet.gitutil import git, git_out
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
    assert run(mono, tmp_path, store, approved)["foo"].status == "unchanged"
    assert store.list(f"s/p/foo/site/{build1}/")  # an unchanged run keeps the grace

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
    assert results["foo"].reason == "re-rendered"
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
    assert result.tip == new_approved
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


def amend(mono, message, when):
    date = f"{when} +0000"
    git(
        "commit",
        "-q",
        "--amend",
        "-m",
        message,
        cwd=mono.path,
        env={"GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date},
    )


def test_stale_allow_rewrite_of_permits_only_one_rewrite(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    allow = f'allow_rewrite_of = "{approved}"'

    amend(mono, "rewritten once", 1767229200)
    tip = export_tip(mono, tmp_path)
    assert run(mono, tmp_path, store, tip, extra=allow)["foo"].status == "published"
    published = store.get("s/p/foo/git/info/refs")

    amend(mono, "rewritten twice", 1767232800)
    tip = export_tip(mono, tmp_path)
    result = run(mono, tmp_path, store, tip, extra=allow)["foo"]
    assert result.status == "failed" and "rewrite" in result.reason
    assert store.get("s/p/foo/git/info/refs") == published


def test_retroactive_previous_paths_is_rejected_as_rewrite(mono, tmp_path):
    from partlet.export import export_project
    from partlet.manifest import Project

    mono.write("legacy/old.txt", "old\n")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    store = LocalStore(tmp_path / "out")
    approved = export_tip(mono, tmp_path)
    assert run(mono, tmp_path, store, approved)["foo"].status == "published"
    before = store.get("s/p/foo/git/info/refs")

    widened = Project("foo", "foo", previous_paths=("legacy",))
    new_tip = export_project(mono.path, "main", widened, tmp_path / "wide.git")
    result = run(mono, tmp_path, store, new_tip, extra='previous_paths = ["legacy"]')[
        "foo"
    ]
    assert result.status == "failed" and "rewrite" in result.reason
    assert store.get("s/p/foo/git/info/refs") == before


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
    """Fails the put of one key, as if the publish died at that point.

    With `after`, the key is written first, as if the publish died just after it.
    """

    def __init__(self, root, fail_key, after=False):
        super().__init__(root)
        self.fail_key = fail_key
        self.after = after

    def put(self, key, data, content_type=None):
        if key != self.fail_key:
            return super().put(key, data, content_type)
        if self.after:
            super().put(key, data, content_type)
        raise OSError(f"interrupted at {key}")


class RecordingStore(LocalStore):
    """Records each deleted key."""

    def __init__(self, root):
        super().__init__(root)
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)
        super().delete(key)


def test_sweep_keeps_live_and_previous_keys_only(mono, tmp_path, first, serve):
    store, approved = first
    out = tmp_path / "out"
    run(mono, tmp_path, store, approved, description="X")
    build_x = json.loads(store.get("s/p/foo/current"))["build"]
    run(mono, tmp_path, store, approved, description="Y")
    build_y = build_id(approved, "Y", "https://partlet.example")

    # Back to X, the build the last publish retired, interrupted after
    # `current` moves but before the sweep.
    interrupted = InterruptedStore(out, "s/p/foo/current", after=True)
    result = run(mono, tmp_path, interrupted, approved, description="X")["foo"]
    assert result.status == "failed"
    assert json.loads(store.get("s/p/foo/current"))["build"] == build_x
    previous = live_keys(store)

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    recording = RecordingStore(out)
    result = run(mono, tmp_path, recording, approved, description="X")["foo"]
    assert result.status == "published"
    # Y was superseded two publishes ago; X and its archives and packs were
    # live until this publish and keep their grace.
    assert store.list(f"s/p/foo/site/{build_y}/") == []
    assert content_keys(store) == live_keys(store) | previous
    assert not set(recording.deleted) & (live_keys(store) | previous)
    assert clone_text(serve, tmp_path) == "one\ntwo\n"


def content_keys(store):
    """Every pack, site build and archive key the project has in the store."""
    return set(
        store.list("s/p/foo/git/objects/pack/")
        + store.list("s/p/foo/site/")
        + store.list("s/p/foo/archive/")
    )


def live_keys(store):
    """The pack, site build and archive keys the live pointers name."""
    current = json.loads(store.get("s/p/foo/current"))
    packs = read_state(store, "s/p/foo/git").packs
    return set(
        [f"s/p/foo/git/objects/pack/{p}.{ext}" for p in packs for ext in PACK_EXTS]
        + store.list(f"s/p/foo/site/{current['build']}/")
        + [f"s/p/foo/archive/{current['tip']}.{fmt}" for fmt in ARCHIVE_FORMATS]
    )


def test_publish_interrupted_before_pointers_leaves_nothing_behind(
    mono, tmp_path, first
):
    store, approved = first
    run(mono, tmp_path, store, approved)
    gen1 = live_keys(store)

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    interrupted = InterruptedStore(tmp_path / "out", "s/p/foo/git/objects/info/packs")
    assert run(mono, tmp_path, interrupted, approved)["foo"].status == "failed"
    orphans = content_keys(store) - gen1
    for kind in ("/git/objects/pack/", "/site/", "/archive/"):
        assert any(kind in key for key in orphans)

    mono.write("foo/a.txt", "one\ntwo\nthree\n")
    mono.commit("c3")
    assert run(mono, tmp_path, store, approved)["foo"].status == "published"
    # The first publish's build and archives stay for one publish of grace;
    # what the interrupted publish uploaded was never live and is gone.
    assert content_keys(store) == live_keys(store) | gen1
    assert not orphans & content_keys(store)


def test_unchanged_run_removes_keys_of_an_abandoned_publish(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved, description="X")

    # A description change dies before `current` names its new site build.
    interrupted = InterruptedStore(tmp_path / "out", "s/p/foo/current")
    result = run(mono, tmp_path, interrupted, approved, description="Y")["foo"]
    assert result.status == "failed"
    build_y = build_id(approved, "Y", "https://partlet.example")
    assert store.list(f"s/p/foo/site/{build_y}/")

    # The change is abandoned, so the next run takes the unchanged shortcut.
    result = run(mono, tmp_path, store, approved, description="X")["foo"]
    assert result.status == "unchanged"
    assert store.list(f"s/p/foo/site/{build_y}/") == []
    assert content_keys(store) == live_keys(store)


def test_publish_interrupted_after_current_still_retires_superseded_keys(
    mono, tmp_path, first
):
    store, approved = first
    run(mono, tmp_path, store, approved)
    gen1 = live_keys(store)

    # An allowed rewrite supersedes every key of the first publish, then dies
    # just after `current` moves.
    amend(mono, "rewritten", 1767229200)
    new_tip = export_tip(mono, tmp_path)
    allow = f'allow_rewrite_of = "{approved}"'
    interrupted = InterruptedStore(tmp_path / "out", "s/p/foo/current", after=True)
    assert run(mono, tmp_path, interrupted, new_tip, extra=allow)["foo"].status == (
        "failed"
    )
    assert json.loads(store.get("s/p/foo/current"))["tip"] == new_tip
    assert not gen1 & live_keys(store)

    # Nothing changed since, so this run takes the unchanged shortcut; the
    # superseded keys are still in their one publish of grace.
    result = run(mono, tmp_path, store, new_tip, extra=allow)["foo"]
    assert result.status == "unchanged"
    assert gen1 <= content_keys(store)
    gen2 = live_keys(store)

    mono.write("foo/a.txt", "one\ntwo\n")
    mono.commit("c2")
    assert run(mono, tmp_path, store, new_tip, extra=allow)["foo"].status == (
        "published"
    )
    assert content_keys(store) == live_keys(store) | gen2
    assert not gen1 & content_keys(store)


def test_consolidated_packs_are_deleted_one_publish_later(
    mono, tmp_path, first, monkeypatch
):
    monkeypatch.setattr(gitstatic, "MAX_PACKS", 2)
    store, approved = first
    run(mono, tmp_path, store, approved)
    mono.write("foo/a.txt", "2\n")
    mono.commit("c2")
    run(mono, tmp_path, store, approved)
    old_packs = read_state(store, "s/p/foo/git").packs
    assert len(old_packs) == 2

    mono.write("foo/a.txt", "3\n")
    mono.commit("c3")
    run(mono, tmp_path, store, approved)
    (full,) = read_state(store, "s/p/foo/git").packs
    pack_keys = set(store.list("s/p/foo/git/objects/pack/"))
    for pack in (*old_packs, full):
        assert f"s/p/foo/git/objects/pack/{pack}.pack" in pack_keys

    mono.write("foo/a.txt", "4\n")
    mono.commit("c4")
    run(mono, tmp_path, store, approved)
    pack_keys = set(store.list("s/p/foo/git/objects/pack/"))
    for pack in old_packs:
        assert f"s/p/foo/git/objects/pack/{pack}.pack" not in pack_keys
    assert f"s/p/foo/git/objects/pack/{full}.pack" in pack_keys


def interrupted_rewrite(mono, tmp_path, approved, fail_key, after=False):
    """Run an allowed rewrite of the first publish that dies at `fail_key`."""
    amend(mono, "rewritten", 1767229200)
    new_tip = export_tip(mono, tmp_path)
    allow = f'allow_rewrite_of = "{approved}"'
    interrupted = InterruptedStore(tmp_path / "out", fail_key, after=after)
    result = run(mono, tmp_path, interrupted, new_tip, extra=allow)["foo"]
    assert result.status == "failed"
    return new_tip, allow


def clone_text(serve, tmp_path):
    clone = tmp_path / f"clone-{len(list(tmp_path.glob('clone-*')))}"
    with serve(tmp_path / "out") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(clone), cwd=tmp_path)
    return (clone / "a.txt").read_text()


def test_abandoned_rewrite_interrupted_before_refs_stays_clonable(
    mono, tmp_path, first, serve
):
    store, approved = first
    original = git_out("rev-parse", "HEAD", cwd=mono.path)
    run(mono, tmp_path, store, approved)

    # The rewrite dies before `info/refs` moves, so refs still need the first
    # publish's pack, which a rewrite drops from the pack list.
    interrupted_rewrite(mono, tmp_path, approved, "s/p/foo/git/info/refs")
    assert clone_text(serve, tmp_path) == "one\n"

    # Abandoned: the export is the published tip again, so this run takes the
    # unchanged shortcut and sweeps.
    git("reset", "-q", "--hard", original, cwd=mono.path)
    assert run(mono, tmp_path, store, approved)["foo"].status == "unchanged"
    assert clone_text(serve, tmp_path) == "one\n"


def test_rewrite_interrupted_before_the_final_pack_list_stays_clonable(
    mono, tmp_path, first, serve
):
    store, approved = first
    run(mono, tmp_path, store, approved)
    new_tip, allow = interrupted_rewrite(
        mono, tmp_path, approved, "s/p/foo/git/HEAD", after=True
    )
    assert clone_text(serve, tmp_path) == "one\n"
    assert run(mono, tmp_path, store, new_tip, extra=allow)["foo"].status == (
        "published"
    )
    assert clone_text(serve, tmp_path) == "one\n"


def test_sweep_deletes_a_cleanup_list_from_before_the_sweep(mono, tmp_path, first):
    store, approved = first
    run(mono, tmp_path, store, approved)
    store.put("s/p/foo/cleanup.json", b"[]\n")
    assert run(mono, tmp_path, store, approved)["foo"].status == "unchanged"
    assert store.get("s/p/foo/cleanup.json") is None
