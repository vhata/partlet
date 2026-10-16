import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from helpers import (
    Repo,
    diff_repo_state,
    repo_state_paths,
    serve_directory,
    snapshot_repo_state,
)

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


def _without_git_vars(env):
    return {k: v for k, v in env.items() if not k.startswith("GIT_")}


def _locate_own_repo() -> tuple[Path, Path] | None:
    """The git dir and common dir of the checkout holding these tests, if any."""
    here = Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--absolute-git-dir", "--git-common-dir"],
            cwd=here,
            env=_without_git_vars(os.environ),
            capture_output=True,
            check=True,
            text=True,
        )
        git_dir, common_dir = proc.stdout.splitlines()[:2]
    except (OSError, subprocess.CalledProcessError, ValueError):
        return None
    return Path(git_dir), (here / common_dir).resolve()


def _backup(state, paths, backup_dir: Path) -> None:
    manifest = []
    for key, path in paths.items():
        data = state[key]
        if data is None:
            manifest.append(f"{key}\t{path}\t(missing)")
            continue
        (backup_dir / key.replace("/", "__")).write_bytes(data)
        manifest.append(f"{key}\t{path}\t{key.replace('/', '__')}")
    (backup_dir / "MANIFEST.txt").write_text("\n".join(manifest) + "\n")


@pytest.fixture(scope="session")
def _repo_tripwire():
    """Fail the run if this repository's git state or ~/.gitconfig changes.

    Must run before `_git_sandbox` replaces HOME, so that it sees the real
    ~/.gitconfig. Disabled outside a git checkout.
    """
    located = _locate_own_repo()
    if located is None:
        yield
        return
    git_dir, common_dir = located
    gitconfig = Path(os.environ.get("HOME", "~")).expanduser() / ".gitconfig"
    paths = repo_state_paths(git_dir, common_dir, gitconfig)
    before = snapshot_repo_state(git_dir, common_dir, gitconfig)
    backup_dir = Path(tempfile.mkdtemp(prefix="partlet-tripwire-"))
    _backup(before, paths, backup_dir)
    yield
    after = snapshot_repo_state(git_dir, common_dir, gitconfig)
    changed = diff_repo_state(before, after)
    if not changed:
        shutil.rmtree(backup_dir, ignore_errors=True)
        return
    # A changed ref may not have been in the original key set.
    after_paths = repo_state_paths(git_dir, common_dir, gitconfig)
    lines = [f"  {key}: {paths.get(key) or after_paths.get(key)}" for key in changed]
    raise RuntimeError(
        "The test run changed a real git file outside its sandbox:\n"
        + "\n".join(lines)
        + f"\nOriginal contents are backed up in {backup_dir}"
        + " (see MANIFEST.txt); restore from there."
    )


def _ceiling_dirs(base: Path) -> str:
    forms = [str(base), str(base.resolve())]
    # On macOS /var is a symlink to /private/var, and likewise /tmp.
    for form in list(forms):
        if form.startswith("/private/"):
            short = form[len("/private") :]
            if Path(short).exists() and str(Path(short).resolve()) == form:
                forms.append(short)
    return ":".join(dict.fromkeys(forms))


@pytest.fixture(scope="session", autouse=True)
def _git_sandbox(tmp_path_factory, _repo_tripwire):
    """Run every test with git cut off from the user's real repositories and config."""
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(_GITCONFIG)
    with pytest.MonkeyPatch.context() as mp:
        for name in [k for k in os.environ if k.startswith("GIT_")]:
            mp.delenv(name)
        mp.setenv("HOME", str(home))
        mp.setenv("XDG_CONFIG_HOME", str(home / ".config"))
        mp.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
        mp.setenv("GIT_CONFIG_NOSYSTEM", "1")
        mp.setenv(
            "GIT_CEILING_DIRECTORIES", _ceiling_dirs(tmp_path_factory.getbasetemp())
        )
        yield


@pytest.fixture
def mono(tmp_path):
    return Repo(tmp_path / "mono")


@pytest.fixture
def serve():
    return serve_directory
