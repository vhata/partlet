"""Run every test with git cut off from real repositories and the user's config.

Three layers, earliest first:

1. At import, inherited `GIT_*` variables are removed from the process, so
   nothing that happens during collection can act on an enclosing repository.
2. `pytest_sessionstart` arms a tripwire on this project's own repository and
   the user's git config, and `pytest_sessionfinish` fails the run if they
   changed.
3. The session fixture `_git_sandbox` moves HOME, the global git config and
   the working directory into pytest's temporary area, and sets
   GIT_CEILING_DIRECTORIES so repository discovery cannot leave it.
"""

import os
from pathlib import Path

import pytest
from helpers import (
    Repo,
    RepoTripwire,
    TripwireError,
    serve_directory,
    tripwire_exit_status,
    user_gitconfig_paths,
)

# Captured before anything is stripped; the tripwire needs the user's real
# HOME, XDG_CONFIG_HOME and GIT_CONFIG_GLOBAL.
_ORIGINAL_ENV = dict(os.environ)

for _name in [k for k in os.environ if k.startswith("GIT_")]:
    del os.environ[_name]

_GITCONFIG = """\
[user]
\tname = Test Author
\temail = author@example.com
[init]
\tdefaultBranch = main
[commit]
\tgpgsign = false
[tag]
\tgpgsign = false
"""

_tripwire: RepoTripwire | None = None


def pytest_sessionstart(session):
    global _tripwire
    _tripwire = RepoTripwire(
        Path(__file__).resolve().parent, user_gitconfig_paths(_ORIGINAL_ENV)
    )


def pytest_sessionfinish(session, exitstatus):
    if _tripwire is None:
        return
    try:
        _tripwire.check()
    except TripwireError as exc:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line("")
            reporter.write_sep("=", "REPOSITORY TRIPWIRE FIRED", red=True, bold=True)
            reporter.write_line(str(exc))
        else:
            print(exc)
        session.exitstatus = tripwire_exit_status(exitstatus)


def pytest_terminal_summary(terminalreporter):
    if _tripwire is not None:
        for note in _tripwire.notes:
            terminalreporter.write_line(note, yellow=True)


def _ceiling_dirs(base: Path) -> str:
    # Git never treats the starting directory itself as a ceiling, so the
    # ceiling is basetemp's parent: even a git call run directly in basetemp
    # cannot climb out. On macOS the temp path can appear as /var/... and as
    # /private/var/..., so list every form.
    parent = base.parent
    forms = [str(parent), str(parent.resolve())]
    for form in list(forms):
        if form.startswith("/private/"):
            short = form[len("/private") :]
            if Path(short).exists() and str(Path(short).resolve()) == form:
                forms.append(short)
    return ":".join(dict.fromkeys(forms))


@pytest.fixture(scope="session", autouse=True)
def _git_sandbox(tmp_path_factory):
    """Run every test with git cut off from the user's real repositories and config."""
    base = tmp_path_factory.getbasetemp()
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(_GITCONFIG)
    cwd = base / "cwd"
    cwd.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        for name in [k for k in os.environ if k.startswith("GIT_")]:
            mp.delenv(name)
        mp.setenv("HOME", str(home))
        mp.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        mp.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
        mp.setenv("GIT_CONFIG_NOSYSTEM", "1")
        mp.setenv("GIT_CEILING_DIRECTORIES", _ceiling_dirs(base))
        # Relative paths and Path.cwd() must not lead back to the real checkout.
        mp.chdir(cwd)
        yield


@pytest.fixture
def mono(tmp_path):
    return Repo(tmp_path / "mono")


@pytest.fixture
def serve():
    return serve_directory
