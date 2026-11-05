"""The CLI teaches its workflow without running tools or changing state."""

import pytest

from partlet import cli


@pytest.fixture
def no_dispatch(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("help must not dispatch commands or change signal handlers")

    monkeypatch.setattr(cli, "COMMANDS", dict.fromkeys(cli.COMMANDS, unexpected))
    monkeypatch.setattr(cli.signal, "signal", unexpected)


@pytest.mark.parametrize("args", [[], ["worker"]])
def test_bare_command_shows_contextual_help(args, no_dispatch, capsys):
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert not output.err
    assert "usage: partlet" in output.out
    assert "commands:" in output.out
    if args:
        assert "partlet worker COMMAND --help" in output.out
        assert "partlet worker preview --config" in output.out
    else:
        assert "partlet review foo --first-publish" in output.out
        assert "partlet build --scan --out" in output.out


def test_no_process_arguments_shows_help(monkeypatch, no_dispatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["partlet"])
    assert cli.main() == 0
    assert "usage: partlet" in capsys.readouterr().out


@pytest.mark.parametrize(
    "command",
    [
        [],
        ["review"],
        ["build"],
        ["publish"],
        ["worker"],
        ["worker", "init"],
        ["worker", "login"],
        ["worker", "whoami"],
        ["worker", "preview"],
        ["worker", "deploy"],
        ["setup"],
        ["unpublish"],
        ["unlock"],
    ],
)
def test_explicit_help_has_examples_without_dispatch(command, no_dispatch, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([*command, "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr()
    assert not output.err
    assert "usage: partlet" in output.out
    assert "partlet review foo" in output.out or "Examples:" in output.out
    if command in ([], ["worker"]):
        assert "COMMAND ..." in output.out
        assert "{" not in output.out.splitlines()[0]


@pytest.mark.parametrize(
    "args",
    [
        ["unknown"],
        ["worker", "unknown"],
        ["review"],
        ["build"],
        ["worker", "init"],
        ["worker", "deploy"],
        ["worker", "preview"],
        ["setup", "--unknown"],
        ["review", "foo", "--first-publish", "--published-tip", "none"],
        ["review", "foo", "--published-tip", "a" * 40, "--first-publish"],
    ],
)
def test_incomplete_or_invalid_commands_remain_errors(args, no_dispatch, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert "error:" in output.err
    assert not output.out


def test_first_publish_is_compatible_with_published_tip_override():
    parser = cli._parser()
    first = parser.parse_args(["review", "foo", "--first-publish"])
    previous = parser.parse_args(["review", "foo", "--published-tip", "none"])
    assert vars(first) == vars(previous)
    assert first.published_tip == "none"
    assert parser.parse_args(["review", "foo"]).published_tip is None
    sha = "a" * 40
    assert (
        parser.parse_args(["review", "foo", "--published-tip", sha]).published_tip
        == sha
    )


def test_first_publish_approves_real_history_without_public_site(mono, monkeypatch):
    from partlet.manifest import load_manifest

    mono.write("foo/README.md", "# Public project\n")
    mono.commit("add project")
    mono.write(
        "partlet.toml",
        '[site]\nsource = "s"\nbase_url = "https://partlet.example"\n'
        '[projects.foo]\npath = "foo"\n',
    )
    mono.commit("configure project")

    def unexpected_fetch(*args, **kwargs):
        pytest.fail("first publication must not contact the public site")

    pages = []
    monkeypatch.setattr(cli, "fetch_published_tip", unexpected_fetch)
    monkeypatch.setattr(cli.pydoc, "pager", pages.append)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert cli.main(["review", "foo", "--repo", str(mono.path), "--first-publish"]) == 0
    project = load_manifest(mono.path / "partlet.toml").projects["foo"]
    assert project.approved is not None
    assert pages and "README.md" in pages[0]
