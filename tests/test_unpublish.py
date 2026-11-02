import json
import os

import pytest
from helpers import export_tip

from partlet.cli import main
from partlet.manifest import parse_manifest
from partlet.publish import publish_all, unpublish_project
from partlet.store import LocalStore, R2Store

SITE = """
[site]
source = "s"
base_url = "https://partlet.example"
"""


@pytest.fixture(params=["local", "r2"])
def published(request, mono, tmp_path):
    """foo and foobar published; returns the store and foobar's keys."""
    if request.param == "local":
        store = LocalStore(tmp_path / "out")
    else:
        store = R2Store(request.getfixturevalue("r2_config"), page_size=2)
    mono.write("foo/a.txt", "a\n")
    mono.write("foobar/b.txt", "b\n")
    mono.commit("c1")
    tips = {name: export_tip(mono, tmp_path, name) for name in ("foo", "foobar")}
    m = parse_manifest(
        SITE
        + "".join(
            f'[projects.{n}]\npath = "{n}"\napproved = "{t}"\n' for n, t in tips.items()
        )
    )
    results = publish_all(mono.path, m, store, tmp_path / "work")
    assert [r.status for r in results] == ["published", "published"]
    return store, {k: store.get(k) for k in store.list("s/p/foobar/")}


def test_unpublish_removes_every_key_and_the_index_entry(published):
    store, foobar = published
    site = parse_manifest(SITE).site
    assert unpublish_project(store, site, "foo") > 5
    assert store.list("s/p/foo/") == []
    assert {k: store.get(k) for k in store.list("s/p/foobar/")} == foobar
    assert [p["name"] for p in json.loads(store.get("s/index.json"))] == ["foobar"]
    assert b'href="/foo"' not in store.get("s/index.html")
    assert b'href="/foobar"' in store.get("s/index.html")


def test_unpublish_resumes_after_an_interruption(published):
    store, _ = published
    site = parse_manifest(SITE).site

    class DiesAfterThreeDeletes:
        def __init__(self, inner):
            self.inner, self.deletes = inner, 0

        def delete(self, key):
            self.deletes += 1
            if self.deletes > 3:
                raise OSError("interrupted")
            self.inner.delete(key)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    with pytest.raises(OSError):
        unpublish_project(DiesAfterThreeDeletes(store), site, "foo")
    assert store.get("s/p/foo/current") is None
    assert [p["name"] for p in json.loads(store.get("s/index.json"))] == ["foobar"]
    assert store.list("s/p/foo/")
    unpublish_project(store, site, "foo")
    assert store.list("s/p/foo/") == []


@pytest.mark.parametrize("name", ["", "../x", "foo/", "Foo", "foo.git"])
def test_invalid_names_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        unpublish_project(LocalStore(tmp_path), parse_manifest(SITE).site, name)


def write_manifest(mono, body=""):
    mono.write("partlet.toml", SITE + body)


def test_cli_refuses_a_project_still_approved(mono, tmp_path, capsys):
    write_manifest(mono, f'[projects.foo]\npath = "foo"\napproved = "{"a" * 40}"\n')
    args = ["unpublish", "foo", "--repo", str(mono.path), "--out", str(tmp_path)]
    assert main([*args, "--yes"]) == 2
    assert "still approved" in capsys.readouterr().err


def test_cli_asks_before_deleting(mono, tmp_path, monkeypatch):
    write_manifest(mono)
    out = tmp_path / "out"
    LocalStore(out).put("s/p/foo/current", b"{}")
    args = ["unpublish", "foo", "--repo", str(mono.path), "--out", str(out)]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    assert main(args) == 1
    assert LocalStore(out).get("s/p/foo/current") == b"{}"
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main(args) == 0
    assert LocalStore(out).list("s/p/foo/") == []
    assert LocalStore(out).get("s/lock") is None


@pytest.mark.parametrize("published", ["r2"], indirect=True)
def test_cli_unpublish_from_r2(mono, tmp_path, r2_env, published):
    store, _ = published
    write_manifest(mono)
    assert main(["unpublish", "foo", "--repo", str(mono.path), "--yes"]) == 0
    assert store.list("s/p/foo/") == []


def test_cli_unlock(mono, tmp_path, monkeypatch, capsys):
    write_manifest(mono)
    out = tmp_path / "out"
    LocalStore(out).put("s/lock", b'{"holder": "dead run", "since": "then"}')
    args = ["unlock", "--repo", str(mono.path), "--out", str(out)]
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert main(args) == 0
    assert "locked by dead run" in capsys.readouterr().out
    assert LocalStore(out).get("s/lock") is None
    assert main(args) == 0
    assert "not locked" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["unpublish", "unlock"])
def test_local_commands_forget_credentials(mono, tmp_path, monkeypatch, command):
    write_manifest(mono)
    monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", "synthetic-key")
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", "synthetic-secret")
    args = [
        command,
        *(["foo"] if command == "unpublish" else []),
        "--repo",
        str(mono.path),
        "--out",
        str(tmp_path / "out"),
        "--yes",
    ]
    assert main(args) == 0
    assert "PARTLET_R2_ACCESS_KEY_ID" not in os.environ
    assert "PARTLET_R2_SECRET_ACCESS_KEY" not in os.environ


def test_unlock_cannot_delete_a_replacement_created_while_answering(
    mono, tmp_path, monkeypatch, capsys
):
    write_manifest(mono)
    out = tmp_path / "out"
    store = LocalStore(out)
    store.put("s/lock", b'{"holder": "stopped", "token": "old"}')
    replacement = b'{"holder": "new live publisher", "token": "new"}'

    def answer(_prompt):
        store.put("s/lock", replacement)
        return "y"

    monkeypatch.setattr("builtins.input", answer)
    assert main(["unlock", "--repo", str(mono.path), "--out", str(out)]) == 1
    assert store.get("s/lock") == replacement
    assert "lock changed" in capsys.readouterr().err


def test_end_of_input_does_not_delete(mono, tmp_path, monkeypatch):
    write_manifest(mono)
    out = tmp_path / "out"
    store = LocalStore(out)
    store.put("s/lock", b'{"holder": "unknown"}')

    def eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert main(["unlock", "--repo", str(mono.path), "--out", str(out)]) == 1
    assert store.get("s/lock") is not None
