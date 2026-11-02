import pytest

from partlet.export import export_project
from partlet.gitutil import git
from partlet.manifest import ManifestError, Project, load_manifest
from partlet.review import (
    ReviewError,
    _path_label,
    fetch_published_tip,
    history_paths,
    large_files,
    run_review,
)
from partlet.scan import Scanner, check_gitleaks
from partlet.site.tree import SIZE_CAP

FAKE_TOKEN = "ghp_" + "1234567890abcdefghij" + "ABCDEFGHIJ123456"

MANIFEST = """# the manifest
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "tools/foo"  # moved here from scripts/foo
"""


@pytest.fixture(scope="module")
def gitleaks():
    return check_gitleaks()


@pytest.fixture
def moved(mono):
    """foo lived in scripts/foo, moved to tools/foo; one file was deleted."""
    mono.write("scripts/foo/a.txt", "a\n")
    mono.write("scripts/foo/old.txt", "old\n")
    mono.commit("c1")
    mono.rm("scripts/foo/old.txt")
    mono.commit("drop old")
    mono.mv("scripts/foo", "tools/foo")
    mono.write("tools/foo/big.bin", b"\0" * (SIZE_CAP + 1))
    mono.commit("move")
    mono.write("partlet.toml", MANIFEST)
    mono.commit("manifest")
    return mono


def review(mono, tmp_path, gitleaks, answer="y", published=None, allow_rewrite=False):
    pages = []
    code = run_review(
        mono.path,
        mono.path / "partlet.toml",
        "foo",
        tmp_path / f"review-{len(list(tmp_path.glob('review-*')))}",
        scanner=Scanner(gitleaks, mono.path),
        published_tip=published,
        allow_rewrite=allow_rewrite,
        confirm=lambda prompt: answer == "y",
        pager=pages.append,
    )
    return code, pages[0]


def test_report_and_approval(moved, tmp_path, gitleaks):
    code, page = review(moved, tmp_path, gitleaks)
    assert code == 0
    tip = load_manifest(moved.path / "partlet.toml").projects["foo"].approved
    assert f"Export tip:    {tip} (1 commits)" in page
    assert "Published tip: none (first publication)" in page
    assert "    a.txt" in page
    assert f"  {SIZE_CAP + 1:>12} big.bin" in page
    assert "Test Author <author@example.com>" in page
    assert "0 finding(s)" in page
    assert "scripts/foo: consider adding it to previous_paths" in page
    assert "scripts/foo/a.txt -> tools/foo/a.txt" in page
    text = (moved.path / "partlet.toml").read_text()
    assert text.startswith("# the manifest\n")
    assert 'path = "tools/foo"  # moved here from scripts/foo' in text


def test_deleted_paths_are_marked(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.write("foo/gone.txt", "x\n")
    mono.commit("c1")
    mono.rm("foo/gone.txt")
    mono.commit("c2")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    _, page = review(mono, tmp_path, gitleaks, answer="n")
    assert "  D gone.txt" in page
    assert "    a.txt" in page


def test_paths_only_merges_touched_are_listed(mono, tmp_path, gitleaks):
    # A file that one merge adds and a later merge removes appears in no
    # ordinary commit's diff.
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    for n, change in ((1, "add"), (2, "remove")):
        git("checkout", "-q", "-b", f"side{n}", cwd=mono.path)
        mono.write(f"foo/side{n}.txt", f"{n}\n")
        mono.commit(f"side{n}")
        git("checkout", "-q", "main", cwd=mono.path)
        mono.write(f"foo/main{n}.txt", f"{n}\n")
        mono.commit(f"main{n}")
        git("merge", "-q", "--no-ff", "--no-commit", f"side{n}", cwd=mono.path)
        if change == "add":
            mono.write("foo/only-in-merges.txt", "m\n")
        else:
            mono.rm("foo/only-in-merges.txt")
        mono.commit(f"merge side{n}, {change} a file")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    _, page = review(mono, tmp_path, gitleaks, answer="n")
    assert "  D only-in-merges.txt" in page


def test_declining_leaves_the_manifest(moved, tmp_path, gitleaks):
    before = (moved.path / "partlet.toml").read_text()
    code, _ = review(moved, tmp_path, gitleaks, answer="n")
    assert code == 1
    assert (moved.path / "partlet.toml").read_text() == before


def test_findings_block_approval(mono, tmp_path, gitleaks):
    mono.write("foo/config.py", f'TOKEN = "{FAKE_TOKEN}"\n')
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    code, page = review(mono, tmp_path, gitleaks)
    assert code == 1
    assert "github-pat in config.py:1" in page
    assert "fingerprint:" in page
    assert FAKE_TOKEN not in page
    assert load_manifest(mono.path / "partlet.toml").projects["foo"].approved is None


def test_rewrite_needs_allow_rewrite(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    unrelated = "b" * 40  # a published tip that is not in this history
    code, page = review(mono, tmp_path, gitleaks, published=unrelated)
    assert code == 1
    assert "this is a rewrite" in page
    code, _ = review(mono, tmp_path, gitleaks, published=unrelated, allow_rewrite=True)
    assert code == 0
    project = load_manifest(mono.path / "partlet.toml").projects["foo"]
    assert project.allow_rewrite_of == unrelated
    assert project.approved == export_project(
        mono.path, "main", Project("foo", "foo"), tmp_path / "probe.git"
    )


def test_allow_rewrite_without_a_rewrite_is_refused(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    with pytest.raises(ReviewError, match="nothing is published"):
        review(mono, tmp_path, gitleaks, allow_rewrite=True)


def test_fetch_published_tip(tmp_path, serve):
    (tmp_path / "foo" / "info").mkdir(parents=True)
    (tmp_path / "foo" / "info" / "refs").write_text(f"{'c' * 40}\trefs/heads/main\n")
    with serve(tmp_path) as base:
        assert fetch_published_tip(base, "foo") == "c" * 40
        assert fetch_published_tip(base, "bar") is None


@pytest.mark.parametrize(
    "body",
    [
        "not a refs advertisement\n",
        f"{'a' * 40}\trefs/heads/main\n{'b' * 40}\trefs/heads/main\n",
        "x" * (1024 * 1024 + 1),
    ],
)
def test_bad_refs_response_cannot_approve(tmp_path, serve, body):
    info = tmp_path / "foo" / "info"
    info.mkdir(parents=True)
    (info / "refs").write_text(body)
    with serve(tmp_path) as base, pytest.raises(ReviewError):
        fetch_published_tip(base, "foo")


def test_large_file_report_includes_deleted_names_and_shared_blobs(mono):
    content = b"\0" * 24
    mono.write("a space.bin", content)
    mono.write("other.bin", content)
    mono.commit("two names of the same large blob")
    mono.rm("a space.bin")
    mono.rm("other.bin")
    mono.write("tiny.txt", "a\n")
    mono.commit("remove both large files")
    assert large_files(mono.path, cap=20) == (
        ("a space.bin", 24),
        ("other.bin", 24),
    )


def test_historical_byte_paths_remain_distinct_and_display_safely(mono):
    mono.commit_raw(
        {b"bad-\xff": b"a\n", b"bad-\\xff": b"b\n", b"line\nbreak": b"c\n"},
        "unusual historical paths",
    )
    paths = [path for path, _deleted in history_paths(mono.path)]
    assert len(paths) == 3
    labels = {_path_label(path) for path in paths}
    assert labels == {r"bad-\xff", r"bad-\\xff", r"line\nbreak"}


def test_manifest_change_while_answering_is_not_approved(moved, tmp_path, gitleaks):
    path = moved.path / "partlet.toml"
    changed = path.read_text().replace('path = "tools/foo"', 'path = "other"')

    def answer(_prompt):
        path.write_text(changed)
        return True

    with pytest.raises(ManifestError, match="changed during review"):
        run_review(
            moved.path,
            path,
            "foo",
            tmp_path / "changed-review",
            scanner=Scanner(gitleaks, moved.path),
            published_tip=None,
            allow_rewrite=False,
            confirm=answer,
            pager=lambda page: None,
        )
    assert path.read_text() == changed


def test_allow_rewrite_still_requires_answer(mono, tmp_path, gitleaks):
    mono.write("foo/a.txt", "a\n")
    mono.commit("c1")
    mono.write("partlet.toml", MANIFEST.replace("tools/foo", "foo"))
    mono.commit("manifest")
    before = (mono.path / "partlet.toml").read_bytes()
    code, _ = review(
        mono, tmp_path, gitleaks, answer="n", published="b" * 40, allow_rewrite=True
    )
    assert code == 1
    assert (mono.path / "partlet.toml").read_bytes() == before
