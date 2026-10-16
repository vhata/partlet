import pytest

from partlet.store import LocalStore


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


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/."])
def test_rejects_bad_keys(tmp_path, key):
    with pytest.raises(ValueError):
        LocalStore(tmp_path).put(key, b"x")
