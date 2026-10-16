import pytest
from helpers import Repo, serve_directory


@pytest.fixture
def mono(tmp_path):
    return Repo(tmp_path / "mono")


@pytest.fixture
def serve():
    return serve_directory
