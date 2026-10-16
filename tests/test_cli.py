from partlet.cli import main
from partlet.export import export_project
from partlet.gitutil import git
from partlet.manifest import Project


def test_build_end_to_end_and_clone(mono, tmp_path, serve, capsys):
    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    tip = export_project(
        mono.path, "main", Project("foo", "foo"), tmp_path / "probe.git"
    )
    mono.write(
        "partlet.toml",
        f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{tip}"
""",
    )
    mono.commit("add manifest")  # does not touch foo/, so the export tip is unchanged

    out = tmp_path / "out"
    assert main(["build", "--repo", str(mono.path), "--out", str(out)]) == 0
    assert "foo" in capsys.readouterr().out
    with serve(out) as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "README.md").read_text() == "# Foo\n"


def test_build_reports_failures_with_exit_code(mono, tmp_path):
    mono.write(
        "partlet.toml",
        """
[site]
source = "s"
base_url = "https://x"

[projects.foo]
path = "missing"
approved = "0000000000000000000000000000000000000000"
""",
    )
    mono.commit("c1")
    assert (
        main(["build", "--repo", str(mono.path), "--out", str(tmp_path / "out")]) == 1
    )


def test_bad_manifest_exit_code(mono, tmp_path, capsys):
    mono.write("partlet.toml", "[site\n")
    mono.commit("c1")
    assert (
        main(["build", "--repo", str(mono.path), "--out", str(tmp_path / "out")]) == 2
    )
    assert "invalid TOML" in capsys.readouterr().err
