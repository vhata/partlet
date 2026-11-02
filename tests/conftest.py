"""Run every test with git cut off from real repositories and the user's config.

Three layers, earliest first:

1. At import, inherited Git/tool configuration, cloud credentials and GitHub
   output file variables are removed from the process.
2. `pytest_sessionstart` arms a tripwire on this project's own repository and
   the user's git config before entering the sandbox.
3. Before collection, the same hook moves HOME, the global git config and
   the working directory into pytest's temporary area, and sets
   GIT_CEILING_DIRECTORIES so repository discovery cannot leave it. It also
   points AWS at missing config files and guards TCP connections before
   collection, allowing loopback only. DNS, UDP and child processes are not
   covered by the Python socket guard.

`pytest_sessionfinish` fails the run if watched state changed. Configuration
cleanup restores the original environment and working directory, including
for collect-only runs and collection errors.
"""

import ipaddress
import os
import socket
from pathlib import Path

import pytest
from helpers import (
    CLOUD_PREFIXES,
    GITHUB_FILE_VARS,
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
_sandbox = pytest.MonkeyPatch()

for _name in [k for k in os.environ if k.startswith(("GIT_", *CLOUD_PREFIXES))]:
    _sandbox.delenv(_name)
for _name in GITHUB_FILE_VARS:
    _sandbox.delenv(_name, raising=False)

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


def pytest_configure(config):
    config.add_cleanup(_sandbox.undo)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    global _tripwire
    _tripwire = RepoTripwire(
        Path(__file__).resolve().parent, user_gitconfig_paths(_ORIGINAL_ENV)
    )
    # Pytest creates its shared factory during configuration. Using that
    # same factory keeps collection and tmp_path fixtures in one sandbox.
    _git_sandbox(session.config._tmp_path_factory)


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


class NetworkBlocked(OSError):
    """A test tried to connect to a non-loopback address."""


def _is_loopback(host: str) -> bool:
    # Numeric addresses only: trusting a hostname would depend on DNS.
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _guard(real):
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_loopback(
            str(address[0])
        ):
            raise NetworkBlocked(f"test sandbox: connection to {address[0]} blocked")
        return real(sock, address)

    return connect


def _git_sandbox(tmp_path_factory):
    """Isolate Git before pytest imports test modules, without needing a fixture."""
    base = tmp_path_factory.getbasetemp()
    home = tmp_path_factory.mktemp("home")
    (home / ".config").mkdir()
    gitconfig = home / ".gitconfig"
    gitconfig.write_text(_GITCONFIG)
    cwd = base / "cwd"
    cwd.mkdir()
    for name in [k for k in os.environ if k.startswith(("GIT_", *CLOUD_PREFIXES))]:
        _sandbox.delenv(name)
    _sandbox.setenv("HOME", str(home))
    _sandbox.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    _sandbox.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    _sandbox.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _sandbox.setenv("GIT_CEILING_DIRECTORIES", _ceiling_dirs(base))
    _sandbox.setenv("AWS_CONFIG_FILE", str(home / ".aws" / "config"))
    _sandbox.setenv("AWS_SHARED_CREDENTIALS_FILE", str(home / ".aws" / "credentials"))
    _sandbox.setenv("AWS_EC2_METADATA_DISABLED", "true")
    _sandbox.setattr(socket.socket, "connect", _guard(socket.socket.connect))
    _sandbox.setattr(socket.socket, "connect_ex", _guard(socket.socket.connect_ex))
    # Relative paths and Path.cwd() must not lead back to the real checkout.
    _sandbox.chdir(cwd)


@pytest.fixture
def mono(tmp_path):
    return Repo(tmp_path / "mono")


@pytest.fixture
def serve():
    return serve_directory


@pytest.fixture(scope="session")
def moto_endpoint():
    from moto.server import ThreadedMotoServer

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    try:
        yield f"http://{host}:{port}"
    finally:
        server.stop()


@pytest.fixture
def r2_config(moto_endpoint):
    import uuid

    import boto3
    from helpers import FAKE_R2_KEY_ID, FAKE_R2_SECRET

    from partlet.r2 import R2Config

    bucket = f"partlet-test-{uuid.uuid4().hex[:12]}"
    boto3.client(
        "s3",
        endpoint_url=moto_endpoint,
        region_name="us-east-1",
        aws_access_key_id=FAKE_R2_KEY_ID,
        aws_secret_access_key=FAKE_R2_SECRET,
    ).create_bucket(Bucket=bucket)
    return R2Config(bucket, moto_endpoint, FAKE_R2_KEY_ID, FAKE_R2_SECRET)


@pytest.fixture
def r2_env(r2_config, monkeypatch):
    monkeypatch.setenv("PARTLET_R2_ENDPOINT", r2_config.endpoint_url)
    monkeypatch.setenv("PARTLET_R2_BUCKET", r2_config.bucket)
    monkeypatch.setenv("PARTLET_R2_ACCESS_KEY_ID", r2_config.access_key_id)
    monkeypatch.setenv("PARTLET_R2_SECRET_ACCESS_KEY", r2_config.secret_access_key)
    return r2_config
