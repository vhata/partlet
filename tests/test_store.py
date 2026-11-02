import stat

import pytest

from partlet import store
from partlet.store import LocalPathError, LocalStore


def test_put_get_delete(tmp_path):
    s = LocalStore(tmp_path)
    assert s.get("a/b.txt") is None
    s.put("a/b.txt", b"hello")
    assert s.get("a/b.txt") == b"hello"
    assert (tmp_path / "a" / "b.txt").read_bytes() == b"hello"
    s.put("a/b.txt", b"again")
    assert s.get("a/b.txt") == b"again"
    s.delete("a/b.txt")
    s.delete("a/b.txt")
    assert s.get("a/b.txt") is None


def test_list_and_list_dirs(tmp_path):
    s = LocalStore(tmp_path)
    for key in [
        "src/p/foo/current",
        "src/p/foo/git/HEAD",
        "src/p/bar/current",
        "src/index.html",
    ]:
        s.put(key, b"x")
    assert s.list("src/p/foo/") == ["src/p/foo/current", "src/p/foo/git/HEAD"]
    assert s.list("src/p/f") == ["src/p/foo/current", "src/p/foo/git/HEAD"]
    assert s.list_dirs("src/p/") == ["bar", "foo"]
    assert s.list_dirs("missing/") == []


def test_names_with_spaces_and_unicode(tmp_path):
    s = LocalStore(tmp_path)
    s.put("p/site/raw/my file #1 é.txt", b"x")
    assert s.list("p/site/raw/") == ["p/site/raw/my file #1 é.txt"]


@pytest.mark.parametrize(
    "keys",
    [
        ["raw/A.txt", "raw/a.txt"],
        ["raw/é.txt", "raw/e\u0301.txt"],
        ["raw/Docs/a", "raw/docs/b"],
        ["raw/É/a", "raw/E\u0301/b"],
        ["raw/A", "raw/a/leaf"],
    ],
)
def test_validate_keys_uses_filesystem_identity(tmp_path, keys):
    s = LocalStore(tmp_path / "out")
    s.put("existing", b"keep")
    # Measure this volume independently of the implementation under test.
    probe = tmp_path / "probe"
    probe.mkdir()
    parts = [key.split("/")[1] for key in keys]
    (probe / parts[0]).touch()
    aliases = (probe / parts[1]).exists()
    if aliases:
        with pytest.raises(LocalPathError, match="alias|cannot be represented"):
            s.validate_keys(keys)
    else:
        s.validate_keys(keys)
    assert s.list("") == ["existing"]
    assert s.get("existing") == b"keep"
    assert list(s.root.iterdir()) == [s.root / "existing"]


def test_validate_keys_keeps_supported_names_and_rejects_file_directory(tmp_path):
    s = LocalStore(tmp_path / "out")
    keys = ["raw/my file #1 é.txt", "raw/docs/a", "raw/docs/b"]
    s.validate_keys(keys)
    assert list(s.root.iterdir()) == []
    with pytest.raises(LocalPathError):
        s.validate_keys(["raw/a", "raw/a/leaf"])
    assert list(s.root.iterdir()) == []


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/."])
def test_rejects_bad_keys(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).put(key, b"x")


def test_put_files_are_readable_by_other_users(tmp_path, monkeypatch):
    # The store reads the umask once at import, so pin the value it uses.
    monkeypatch.setattr(store, "_UMASK", 0o022)
    LocalStore(tmp_path).put("a/b.txt", b"x")
    assert stat.S_IMODE((tmp_path / "a" / "b.txt").stat().st_mode) == 0o644


def test_list_includes_project_files_named_like_temp_files(tmp_path):
    s = LocalStore(tmp_path)
    keys = [
        "p/site/raw/.tmp-keep",
        "p/site/raw/.partlet-tmp-keep",
        "p/site/blob/.partlet-tmp-keep",
        "p/site/raw/.partlet-tmp-dir/leaf",
    ]
    for key in keys:
        s.put(key, b"x")
    assert s.list("p/") == sorted(keys)


@pytest.mark.parametrize("parent", ["plain", "É", "E\u0301"])
@pytest.mark.parametrize("fail", [False, True])
def test_list_hides_only_active_temporary_file(tmp_path, monkeypatch, parent, fail):
    s = LocalStore(tmp_path / "out")
    s.put("é/.partlet-tmp-keep", b"committed")
    original_replace = store.os.replace

    def replace(src, dst):
        assert ".partlet-tmp-keep" in " ".join(s.list(""))
        assert all(".partlet-tmp-" not in k or k.endswith("keep") for k in s.list(""))
        if fail:
            raise OSError("interrupted replace")
        original_replace(src, dst)
        assert s.get(f"{parent}/new") == b"new"
        assert any(k.endswith("/new") for k in s.list(""))

    monkeypatch.setattr(store.os, "replace", replace)
    if fail:
        with pytest.raises(OSError, match="interrupted"):
            s.put(f"{parent}/new", b"new")
    else:
        s.put(f"{parent}/new", b"new")
    assert not s._temporary
    assert len(list(s.root.rglob(".partlet-tmp-*"))) == 1


def test_list_includes_abandoned_implementation_temp(tmp_path):
    s = LocalStore(tmp_path)
    (tmp_path / ".partlet-tmp-abandoned").write_bytes(b"orphan")
    assert s.list("") == [".partlet-tmp-abandoned"]
