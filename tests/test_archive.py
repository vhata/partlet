import io
import tarfile
import zipfile

from partlet.archive import make_archives
from partlet.export import export_project
from partlet.manifest import Project


def test_archives_contain_prefixed_files_and_are_deterministic(mono, tmp_path):
    mono.write("foo/a.txt", "alpha\n")
    mono.write("foo/sub/b.txt", "beta\n")
    mono.commit("c1")
    repo = tmp_path / "e.git"
    tip = export_project(mono.path, "main", Project("foo", "foo"), repo)

    first = make_archives(repo, "foo", tip)
    second = make_archives(repo, "foo", tip)
    assert first == second
    assert set(first) == {"tar.gz", "zip"}

    with tarfile.open(fileobj=io.BytesIO(first["tar.gz"]), mode="r:gz") as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
    assert names == ["foo/a.txt", "foo/sub/b.txt"]

    with zipfile.ZipFile(io.BytesIO(first["zip"])) as z:
        assert z.read("foo/a.txt") == b"alpha\n"
