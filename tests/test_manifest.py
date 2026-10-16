import pytest

from partlet.manifest import ManifestError, parse_manifest

FULL = """
[site]
source = "jonathan"
branch = "trunk"
base_url = "https://partlet.example/"
mailmap = ".partlet-mailmap"

[projects.foo]
path = "/tools/foo/"
previous_paths = ["scripts/foo"]
description = "Foo tool"
approved = "3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a"
allow_rewrite_of = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

[projects.bar]
path = "bar"
"""


def test_full_manifest_parses():
    m = parse_manifest(FULL)
    assert m.site.source == "jonathan"
    assert m.site.branch == "trunk"
    assert m.site.base_url == "https://partlet.example"
    assert m.site.mailmap == ".partlet-mailmap"
    foo = m.projects["foo"]
    assert foo.path == "tools/foo"
    assert foo.previous_paths == ("scripts/foo",)
    assert foo.all_paths == ("tools/foo", "scripts/foo")
    assert foo.description == "Foo tool"
    assert foo.approved == "3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a3f9c2e1a"
    assert foo.allow_rewrite_of == "a" * 40


def test_defaults():
    m = parse_manifest(
        '[site]\nsource = "s"\nbase_url = "https://x"\n[projects.bar]\npath = "bar"\n'
    )
    assert m.site.branch == "main"
    assert m.site.mailmap is None
    bar = m.projects["bar"]
    assert bar.previous_paths == ()
    assert bar.description == ""
    assert bar.approved is None
    assert bar.allow_rewrite_of is None


def test_no_projects_is_valid():
    m = parse_manifest('[site]\nsource = "s"\nbase_url = "https://x"\n')
    assert m.projects == {}


@pytest.mark.parametrize(
    "body, message",
    [
        ('[projects.foo]\npath = "foo"\n', r"missing \[site\]"),
        ('[site]\nsource = "s"\n', "base_url"),
        ('[site]\nsource = "Bad"\nbase_url = "https://x"\n', "site.source"),
        (
            '[site]\nsource = "s"\nbase_url = "https://x"\ncolour = "red"\n',
            "unknown key",
        ),
    ],
)
def test_bad_site(body, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(body)


SITE = '[site]\nsource = "s"\nbase_url = "https://x"\n'


@pytest.mark.parametrize(
    "project, message",
    [
        ('[projects.Foo]\npath = "foo"\n', "project name"),
        ('[projects."foo.git"]\npath = "foo"\n', "\\.git"),
        ('[projects.foo]\ndescription = "x"\n', "path"),
        ('[projects.foo]\npath = "../foo"\n', "invalid path"),
        ('[projects.foo]\npath = "a/./b"\n', "invalid path"),
        ('[projects.foo]\npath = "/"\n', "invalid path"),
        ('[projects.foo]\npath = "foo"\napproved = "abc"\n', "approved"),
        ('[projects.foo]\npath = "foo"\nprevious_path = ["old"]\n', "unknown key"),
        ('[projects.foo]\npath = "foo"\nprevious_paths = "old"\n', "previous_paths"),
        ('[projects.foo]\npath = "foo"\nprevious_paths = ["foo"]\n', "duplicate"),
        (
            '[projects.foo]\npath = "foo"\nprevious_paths = ["old", "old/"]\n',
            "duplicate",
        ),
    ],
)
def test_bad_project(project, message):
    with pytest.raises(ManifestError, match=message):
        parse_manifest(SITE + project)


def test_invalid_toml():
    with pytest.raises(ManifestError, match="invalid TOML"):
        parse_manifest("[site\n")
