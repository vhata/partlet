from partlet import gitstatic
from partlet.export import export_project
from partlet.gitstatic import GitState, read_state, upload_pack, write_pointers
from partlet.gitutil import git, git_out
from partlet.manifest import Project
from partlet.store import LocalStore

PREFIX = "s/p/foo/git"


def publish(store, mono, tmp_path, n, full=False):
    repo = tmp_path / f"e{n}.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)
    old = read_state(store, PREFIX)
    plan = upload_pack(store, PREFIX, repo, tip, old, tmp_path / f"w{n}", full=full)
    write_pointers(store, PREFIX, plan, old)
    return tip, plan


def test_read_state_empty(tmp_path):
    assert read_state(LocalStore(tmp_path), PREFIX) == GitState(None, ())


def test_clone_then_pull_over_dumb_http(mono, tmp_path, serve):
    store = LocalStore(tmp_path / "out")
    mono.write("foo/a.txt", "one\n")
    mono.commit("c1")
    tip1, plan1 = publish(store, mono, tmp_path, 1)
    assert read_state(store, PREFIX) == GitState(tip1, plan1.packs)
    assert store.get(f"{PREFIX}/HEAD") == b"ref: refs/heads/main\n"
    assert store.get(f"{PREFIX}/info/refs") == f"{tip1}\trefs/heads/main\n".encode()

    with serve(tmp_path / "out") as base:
        url = f"{base}/{PREFIX}"
        clone = tmp_path / "clone"
        git("clone", "-q", url, str(clone), cwd=tmp_path)
        assert (clone / "a.txt").read_text() == "one\n"

        mono.write("foo/a.txt", "one\ntwo\n")
        mono.commit("c2")
        tip2, plan2 = publish(store, mono, tmp_path, 2)
        assert len(plan2.packs) == 2
        assert plan2.packs[0] == plan1.packs[0]

        git("pull", "-q", "--ff-only", cwd=clone)
        assert git_out("rev-parse", "HEAD", cwd=clone) == tip2
        assert (clone / "a.txt").read_text() == "one\ntwo\n"


def test_consolidates_after_max_packs(mono, tmp_path, monkeypatch):
    monkeypatch.setattr(gitstatic, "MAX_PACKS", 2)
    store = LocalStore(tmp_path / "out")
    plans = []
    for n in range(3):
        mono.write("foo/a.txt", f"{n}\n")
        mono.commit(f"c{n}")
        plans.append(publish(store, mono, tmp_path, n)[1])
    assert len(plans[1].packs) == 2
    assert len(plans[2].packs) == 1
    assert plans[2].packs[0] not in plans[1].packs
