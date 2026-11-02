import pytest

from partlet.manifest import ManifestError, load_manifest, set_project_fields

TEXT = """# Partlet manifest
[site]
source = "s"   # key prefix
base_url = "https://x"

[projects.foo]
path = "foo"  # where it lives
# approved by partlet review
approved = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[projects.bar]
path = "bar"
"""


def test_replaces_and_adds_fields_keeping_comments(tmp_path):
    path = tmp_path / "partlet.toml"
    path.write_text(TEXT)
    set_project_fields(path, "foo", {"approved": "b" * 40})
    set_project_fields(
        path, "bar", {"approved": "c" * 40, "allow_rewrite_of": "d" * 40}
    )
    text = path.read_text()
    assert text.startswith("# Partlet manifest\n")
    assert 'source = "s"   # key prefix' in text
    assert 'path = "foo"  # where it lives\n# approved by partlet review\n' in text
    m = load_manifest(path)
    assert m.projects["foo"].approved == "b" * 40
    assert m.projects["bar"].approved == "c" * 40
    assert m.projects["bar"].allow_rewrite_of == "d" * 40


def test_inline_project_table(tmp_path):
    path = tmp_path / "partlet.toml"
    path.write_text(
        '[site]\nsource = "s"\nbase_url = "x"\n[projects]\nfoo = { path = "foo" }\n'
    )
    set_project_fields(path, "foo", {"approved": "e" * 40})
    assert load_manifest(path).projects["foo"].approved == "e" * 40


@pytest.mark.parametrize(
    "name, fields, message",
    [
        ("missing", {"approved": "b" * 40}, "not in"),
        ("foo", {"colour": "red"}, "not a project key"),
        ("foo", {"approved": "short"}, "40-character"),
    ],
)
def test_refuses_bad_edits_and_leaves_the_file(tmp_path, name, fields, message):
    path = tmp_path / "partlet.toml"
    path.write_text(TEXT)
    with pytest.raises(ManifestError, match=message):
        set_project_fields(path, name, fields)
    assert path.read_text() == TEXT


def test_preserves_line_endings_and_mode(tmp_path):
    path = tmp_path / "partlet.toml"
    path.write_bytes(TEXT.replace("\n", "\r\n").encode())
    path.chmod(0o640)
    set_project_fields(path, "foo", {"approved": "e" * 40})
    assert path.stat().st_mode & 0o777 == 0o640
    assert b'path = "foo"  # where it lives\r\n' in path.read_bytes()
    assert b"\n" not in path.read_bytes().replace(b"\r\n", b"")


def test_changed_manifest_is_never_overwritten(tmp_path):
    path = tmp_path / "partlet.toml"
    changed = TEXT.replace('path = "foo"', 'path = "other"')
    path.write_text(changed)
    with pytest.raises(ManifestError, match="changed during review"):
        set_project_fields(path, "foo", {"approved": "e" * 40}, expected_text=TEXT)
    assert path.read_text() == changed
    assert sorted(p.name for p in tmp_path.iterdir()) == ["partlet.toml"]


def test_failed_replace_leaves_original_and_no_temporary_file(tmp_path, monkeypatch):
    from pathlib import Path

    path = tmp_path / "partlet.toml"
    path.write_text(TEXT)

    def fail_replace(*args):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(ManifestError, match="simulated rename failure"):
        set_project_fields(path, "foo", {"approved": "e" * 40})
    assert path.read_text() == TEXT
    assert sorted(p.name for p in tmp_path.iterdir()) == ["partlet.toml"]
