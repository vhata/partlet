import socket

import boto3
import pytest
from helpers import FAKE_R2_SECRET, mirror_store

from partlet.store import LocalStore, R2Config, R2Store, StoreError


@pytest.fixture(params=["local", "r2"])
def store(request, tmp_path):
    if request.param == "local":
        return LocalStore(tmp_path / "out")
    # A page size of 2 makes every listing below span several pages.
    return R2Store(request.getfixturevalue("r2_config"), page_size=2)


def test_put_get_delete(store):
    assert store.get("a/b.txt") is None
    store.put("a/b.txt", b"hello", "text/plain")
    assert store.get("a/b.txt") == b"hello"
    store.put("a/b.txt", b"again")
    assert store.get("a/b.txt") == b"again"
    store.delete("a/b.txt")
    store.delete("a/b.txt")
    assert store.get("a/b.txt") is None


def test_list_and_list_dirs_page_through_everything(store):
    keys = [f"s/p/foo/site/b/raw/f{i:02}.txt" for i in range(7)]
    for key in [*keys, "s/p/foo/current", "s/p/foobar/current", "s/index.html"]:
        store.put(key, b"x")
    assert store.list("s/p/foo/site/") == keys
    assert store.list("s/p/foo/") == ["s/p/foo/current", *keys]
    assert store.list_dirs("s/p/") == ["foo", "foobar"]
    assert store.list_dirs("missing/") == []
    assert len(store.list("")) == 10


def test_names_with_spaces_and_unicode(store):
    store.put("p/site/raw/my file #1 é.txt", b"x")
    assert store.list("p/site/raw/") == ["p/site/raw/my file #1 é.txt"]
    assert store.get("p/site/raw/my file #1 é.txt") == b"x"


def test_put_if_absent_creates_once(r2_config):
    store = R2Store(r2_config)
    assert store.put_if_absent("s/lock", b"first", "application/json")
    assert not store.put_if_absent("s/lock", b"second")
    assert store.get("s/lock") == b"first"
    store.delete("s/lock")
    assert store.put_if_absent("s/lock", b"third")


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a", "a/."])
def test_rejects_bad_keys(store, key):
    with pytest.raises(ValueError):
        store.put(key, b"x")


def test_missing_bucket_is_an_error_not_a_missing_key(r2_config):
    store = R2Store(
        R2Config("partlet-no-such-bucket", r2_config.endpoint_url, "k", "s")
    )
    with pytest.raises(StoreError, match="NoSuchBucket"):
        store.get("s/p/foo/git/info/refs")


class BrokenBody:
    def __init__(self, failures):
        self.failures = failures

    def read(self):
        from botocore.exceptions import ResponseStreamingError

        if self.failures:
            self.failures -= 1
            raise ResponseStreamingError(error="connection reset")
        return b"data"

    def close(self):
        pass


@pytest.mark.parametrize("failures, expected", [(1, b"data"), (3, None)])
def test_get_retries_a_body_that_fails_to_stream(
    r2_config, monkeypatch, failures, expected
):
    store = R2Store(r2_config, max_attempts=3, retry_delay=0)
    body = BrokenBody(failures)
    monkeypatch.setattr(store._client, "get_object", lambda **kw: {"Body": body})
    if expected is None:
        with pytest.raises(StoreError, match="reading the body"):
            store.get("s/index.html")
    else:
        assert store.get("s/index.html") == expected


def test_content_type_is_stored(r2_config):
    R2Store(r2_config).put("s/index.html", b"<p>", "text/html; charset=utf-8")
    client = boto3.client(
        "s3",
        endpoint_url=r2_config.endpoint_url,
        region_name="us-east-1",
        aws_access_key_id=r2_config.access_key_id,
        aws_secret_access_key=r2_config.secret_access_key,
    )
    head = client.head_object(Bucket=r2_config.bucket, Key="s/index.html")
    assert head["ContentType"] == "text/html; charset=utf-8"


def test_no_ambient_aws_credentials():
    assert boto3.session.Session().get_credentials() is None


def test_from_env_reads_settings_and_removes_the_keys():
    env = {
        "PARTLET_R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
        "PARTLET_R2_ACCESS_KEY_ID": "key-id",
        "PARTLET_R2_SECRET_ACCESS_KEY": "secret-value",
        "PARTLET_R2_BUCKET": "partlet",
        "OTHER": "kept",
    }
    config = R2Config.from_env(env)
    assert config.endpoint_url == (
        "https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com"
    )
    assert config.bucket == "partlet"
    assert config.secret_access_key == "secret-value"
    assert env == {
        "PARTLET_R2_ACCOUNT_ID": "0123456789abcdef0123456789abcdef",
        "PARTLET_R2_BUCKET": "partlet",
        "OTHER": "kept",
    }
    assert "secret-value" not in repr(config)
    assert "key-id" not in repr(config)


def test_from_env_endpoint_override():
    env = {
        "PARTLET_R2_ENDPOINT": "https://0123.eu.r2.cloudflarestorage.com",
        "PARTLET_R2_ACCESS_KEY_ID": "k",
        "PARTLET_R2_SECRET_ACCESS_KEY": "s",
        "PARTLET_R2_BUCKET": "b",
    }
    assert R2Config.from_env(env).endpoint_url == env["PARTLET_R2_ENDPOINT"]


def test_from_env_names_missing_settings_without_values():
    env = {"PARTLET_R2_SECRET_ACCESS_KEY": "secret-value"}
    with pytest.raises(StoreError) as e:
        R2Config.from_env(env)
    message = str(e.value)
    assert "PARTLET_R2_ACCESS_KEY_ID" in message
    assert "PARTLET_R2_BUCKET" in message
    assert "PARTLET_R2_ACCOUNT_ID" in message
    assert "secret-value" not in message
    assert env == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://abc.r2.cloudflarestorage.com",
        "https://user:pw@abc.r2.cloudflarestorage.com",
        "https://abc.r2.cloudflarestorage.com/bucket",
        "ftp://127.0.0.1",
    ],
)
def test_unsafe_endpoints_are_refused(url):
    with pytest.raises(StoreError, match="R2 endpoint"):
        R2Store(R2Config("b", url, "k", "s"))


def test_errors_and_repr_never_contain_the_secret(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # closed again: nothing listens there
    store = R2Store(
        R2Config("b", f"http://127.0.0.1:{port}", "k", FAKE_R2_SECRET),
        max_attempts=1,
    )
    assert FAKE_R2_SECRET not in repr(store)
    with pytest.raises(StoreError) as e:
        store.get("s/index.html")
    assert FAKE_R2_SECRET not in str(e.value)
    assert FAKE_R2_SECRET not in repr(e.value)


def test_mirror_of_r2_store_is_cloneable(r2_config, tmp_path, mono, serve):
    from helpers import export_tip

    from partlet.gitutil import git
    from partlet.manifest import parse_manifest
    from partlet.publish import publish_all

    mono.write("foo/README.md", "# Foo\n")
    mono.commit("c1")
    approved = export_tip(mono, tmp_path)
    m = parse_manifest(f"""
[site]
source = "s"
base_url = "https://partlet.example"

[projects.foo]
path = "foo"
approved = "{approved}"
""")
    store = R2Store(r2_config, page_size=3)
    (result,) = publish_all(mono.path, m, store, tmp_path / "w1")
    assert result.status == "published"
    mirror_store(store, tmp_path / "site")
    with serve(tmp_path / "site") as base:
        git("clone", "-q", f"{base}/s/p/foo/git", str(tmp_path / "clone"), cwd=tmp_path)
    assert (tmp_path / "clone" / "README.md").read_text() == "# Foo\n"


@pytest.mark.parametrize("applied", [False, True])
def test_lost_lock_delete_response_is_not_retried(r2_config, monkeypatch, applied):
    from botocore.exceptions import ConnectionClosedError

    from partlet.lock import LockError, read_lock, store_lock

    first = R2Store(r2_config, max_attempts=3)
    second = R2Store(r2_config)
    next_holder = store_lock(second, "s", "second run")
    client = getattr(first, "_delete_client", first._client)
    transport = client._endpoint.http_session
    send = transport.send
    attempts = 0
    next_held = False

    def lose_response(request):
        nonlocal attempts, next_held
        if request.method != "DELETE":
            return send(request)
        attempts += 1
        if attempts == 1:
            if applied:
                # The real local S3 server applies the delete. Another
                # publisher acquires the now-free lock before the connection
                # loss reaches the first client's retry handler.
                response = send(request)
                response.raw.close()
                next_holder.__enter__()
                next_held = True
            raise ConnectionClosedError(endpoint_url=r2_config.endpoint_url)
        return send(request)

    monkeypatch.setattr(transport, "send", lose_response)
    try:
        with pytest.raises(StoreError), store_lock(first, "s", "first run"):
            assert read_lock(first, "s")["holder"] == "first run"
        assert attempts == 1
        expected = "second run" if applied else "first run"
        assert read_lock(second, "s")["holder"] == expected
        with pytest.raises(LockError):
            store_lock(R2Store(r2_config), "s", "third run").__enter__()
    finally:
        if next_held:
            next_holder.__exit__(None, None, None)


@pytest.mark.parametrize(
    "url",
    [
        "https://u:secret@host",
        "https://[",
        "https://host:bad",
        "https://host:0",
        "https://ho\nst",
    ],
)
def test_endpoint_error_never_echoes_url(url):
    from partlet.store import check_endpoint

    with pytest.raises(StoreError) as exc:
        check_endpoint(url)
    assert url not in str(exc.value)
    assert "secret" not in str(exc.value)


def test_remote_error_messages_are_not_printed(r2_config, monkeypatch):
    from botocore.exceptions import ClientError

    store = R2Store(r2_config)

    def denied(**kw):
        raise ClientError(
            {
                "Error": {"Code": "AccessDenied", "Message": FAKE_R2_SECRET},
                "ResponseMetadata": {"HTTPStatusCode": 403},
            },
            "GetObject",
        )

    monkeypatch.setattr(store._client, "get_object", denied)
    with pytest.raises(StoreError, match="AccessDenied") as exc:
        store.get("s/index.html")
    assert FAKE_R2_SECRET not in str(exc.value)
    assert exc.value.__suppress_context__


@pytest.mark.parametrize("token", [None, "same"])
def test_invalid_pagination_is_an_error(r2_config, monkeypatch, token):
    store = R2Store(r2_config)
    monkeypatch.setattr(
        store._client,
        "list_objects_v2",
        lambda **kw: {"IsTruncated": True, "NextContinuationToken": token},
    )
    with pytest.raises(StoreError, match="continuation token"):
        store.list("s/")


def test_retry_and_checksum_settings(r2_config):
    store = R2Store(r2_config, max_attempts=4)
    assert store._client.meta.config.retries["total_max_attempts"] == 4
    assert store._delete_client.meta.config.retries["total_max_attempts"] == 1
    assert store._client.meta.config.request_checksum_calculation == "when_required"
    assert store._client.meta.config.response_checksum_validation == "when_required"


def test_directory_listing_follows_every_page(r2_config):
    store = R2Store(r2_config, page_size=2)
    names = [f"project-{i}" for i in range(7)]
    for name in names:
        store.put(f"s/p/{name}/current", b"{}")
    assert store.list_dirs("s/p/") == names


def test_streaming_response_is_closed_on_success_and_failure(r2_config, monkeypatch):
    from botocore.exceptions import ResponseStreamingError

    store = R2Store(r2_config, max_attempts=2, retry_delay=0)
    bodies = []

    class Body:
        closed = False

        def read(self):
            if len(bodies) == 1:
                raise ResponseStreamingError(error="connection reset")
            return b"complete"

        def close(self):
            self.closed = True

    def response(**kw):
        body = Body()
        bodies.append(body)
        return {"Body": body}

    monkeypatch.setattr(store._client, "get_object", response)
    assert store.get("s/object") == b"complete"
    assert len(bodies) == 2
    assert all(body.closed for body in bodies)
