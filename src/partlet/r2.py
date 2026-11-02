"""R2 backend for the Store protocol, using the S3-compatible API."""

from __future__ import annotations

import re
import time
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from partlet.store import check_key


class StoreError(Exception):
    """The store could not complete an operation."""


R2_ENV = {
    "account_id": "PARTLET_R2_ACCOUNT_ID",
    "access_key_id": "PARTLET_R2_ACCESS_KEY_ID",
    "secret_access_key": "PARTLET_R2_SECRET_ACCESS_KEY",
    "bucket": "PARTLET_R2_BUCKET",
    "endpoint": "PARTLET_R2_ENDPOINT",
}
ACCOUNT_ID_RE = re.compile(r"[0-9a-f]{32}")
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class R2Config:
    bucket: str
    endpoint_url: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)

    @classmethod
    def from_env(cls, environ: MutableMapping[str, str]) -> R2Config:
        """Read the R2 settings from `environ`, removing the two key variables.

        Removing them means git, git-filter-repo and gitleaks, which partlet runs
        as child processes, never inherit the credentials. PARTLET_R2_ENDPOINT
        replaces the endpoint derived from the account ID, for buckets in a
        jurisdiction (https://<account>.eu.r2.cloudflarestorage.com).
        """
        values = {name: environ.get(var, "").strip() for name, var in R2_ENV.items()}
        for name in ("access_key_id", "secret_access_key"):
            environ.pop(R2_ENV[name], None)
        required = ["access_key_id", "secret_access_key", "bucket"]
        if not values["endpoint"]:
            required.append("account_id")
        missing = [R2_ENV[name] for name in required if not values[name]]
        if missing:
            raise StoreError(f"missing R2 settings: {', '.join(missing)}")
        endpoint = values["endpoint"]
        if not endpoint:
            if not ACCOUNT_ID_RE.fullmatch(values["account_id"]):
                raise StoreError(
                    "PARTLET_R2_ACCOUNT_ID must be a 32-character hexadecimal account ID"
                )
            endpoint = f"https://{values['account_id']}.r2.cloudflarestorage.com"
        return cls(
            values["bucket"],
            endpoint,
            values["access_key_id"],
            values["secret_access_key"],
        )


def check_endpoint(url: str) -> str:
    """Refuse endpoints that would send credentials in clear text or elsewhere."""
    try:
        parts = urlsplit(url)
        plain_loopback = parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
        valid = (
            (parts.scheme == "https" or plain_loopback)
            and parts.hostname
            and parts.username is None
            and parts.password is None
            and parts.path in ("", "/")
            and not parts.query
            and not parts.fragment
            and (parts.port is None or parts.port > 0)
            and not any(c.isspace() or ord(c) < 32 for c in url)
        )
    except ValueError:
        valid = False
    if not valid:
        # A rejected URL may contain credentials; do not echo it.
        raise StoreError(
            "R2 endpoint must be https://<host> (plain http only on loopback)"
        ) from None
    return url


class R2Store:
    """A bucket in Cloudflare R2, through its S3-compatible API.

    R2 is strongly consistent: a read, list or delete that starts after a
    write returns sees that write. Each put replaces the whole object at once,
    so a reader sees the old object or the new one, never a mix.
    """

    def __init__(
        self,
        config: R2Config,
        *,
        page_size: int = 1000,
        max_attempts: int = 5,
        retry_delay: float = 0.5,
    ):
        import boto3
        from botocore.config import Config

        if not 1 <= page_size <= 1000 or max_attempts < 1 or retry_delay < 0:
            raise ValueError("invalid R2 pagination or retry limits")
        if (
            not config.bucket
            or not config.access_key_id
            or not config.secret_access_key
        ):
            raise StoreError("R2 bucket and explicit credentials are required")
        self.bucket = config.bucket
        self.endpoint_url = check_endpoint(config.endpoint_url)
        self._page_size = page_size
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay
        session = boto3.session.Session()
        client_options = {
            "endpoint_url": self.endpoint_url,
            "aws_access_key_id": config.access_key_id,
            "aws_secret_access_key": config.secret_access_key,
        }
        client_config = Config(
            region_name="auto",
            signature_version="s3v4",
            retries={"total_max_attempts": max_attempts, "mode": "standard"},
            connect_timeout=10,
            read_timeout=60,
            # Send and check checksums only where the API requires them,
            # whatever this botocore version's default is.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        )
        self._client = session.client("s3", config=client_config, **client_options)
        # A delete may succeed even when its response is lost. Retrying it
        # could delete a replacement lock acquired by the next publisher.
        # total_max_attempts includes the initial request: one means no retry.
        self._delete_client = session.client(
            "s3",
            config=client_config.merge(
                Config(retries={"total_max_attempts": 1, "mode": "standard"})
            ),
            **client_options,
        )

    def __repr__(self) -> str:
        return f"R2Store(bucket={self.bucket!r}, endpoint_url={self.endpoint_url!r})"

    def _call(self, what: str, method: str, *, client=None, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return getattr(client or self._client, method)(Bucket=self.bucket, **kwargs)
        except ClientError as e:
            error = e.response.get("Error", {})
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = str(error.get("Code", "error"))
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", code):
                code = "error"
            # Server messages and SDK exception text may echo request data.
            raise R2ClientError(
                f"R2 {what}: {code} (HTTP {status})",
                code=code,
                status=status,
            ) from None
        except BotoCoreError as e:
            unknown = (
                "; outcome unknown; verify the stopped holder before recovery"
                if method in ("delete_object", "put_object")
                else ""
            )
            raise StoreError(f"R2 {what}: {type(e).__name__}{unknown}") from None

    def get(self, key: str) -> bytes | None:
        from botocore.exceptions import BotoCoreError

        check_key(key)
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._call(f"get {key}", "get_object", Key=key)
            except R2ClientError as e:
                # Only a missing key; NoSuchBucket is also a 404 and must not
                # read as "nothing published".
                if e.code == "NoSuchKey":
                    return None
                raise
            # botocore retries the request but not the body, which streams
            # afterwards: a dropped connection or short read surfaces here.
            try:
                return response["Body"].read()
            except BotoCoreError as e:
                if attempt == self._max_attempts:
                    raise StoreError(
                        f"R2 get {key}: reading the body: {type(e).__name__}"
                    ) from None
                time.sleep(self._retry_delay * 2 ** (attempt - 1))
            finally:
                response["Body"].close()
        raise AssertionError("unreachable")

    def put(self, key: str, data: bytes, content_type: str | None = None) -> None:
        check_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        self._call(f"put {key}", "put_object", Key=key, Body=data, **extra)

    def put_if_absent(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> bool:
        check_key(key)
        extra = {"ContentType": content_type} if content_type else {}
        try:
            self._call(
                f"create {key}",
                "put_object",
                Key=key,
                Body=data,
                IfNoneMatch="*",
                **extra,
            )
        except R2ClientError as e:
            # 412: the key exists. 409: another conditional write to it is in
            # progress; either way someone else holds it.
            if e.status in (409, 412):
                return False
            raise
        return True

    def delete(self, key: str) -> None:
        check_key(key)
        # An uncertain delete fails the operation; callers must not retry a
        # lock release, because another run may already hold the same key.
        self._call(
            f"delete {key}", "delete_object", client=self._delete_client, Key=key
        )

    def _pages(self, **kwargs) -> Iterator[dict]:
        token = None
        seen = set()
        while True:
            extra = {"ContinuationToken": token} if token else {}
            page = self._call(
                f"list {kwargs.get('Prefix', '')}",
                "list_objects_v2",
                MaxKeys=self._page_size,
                **kwargs,
                **extra,
            )
            yield page
            if not page.get("IsTruncated"):
                return
            token = page.get("NextContinuationToken")
            if not token or token in seen:
                raise StoreError("R2 list: invalid continuation token")
            seen.add(token)

    def list(self, prefix: str) -> list[str]:
        return sorted(
            obj["Key"]
            for page in self._pages(Prefix=prefix)
            for obj in page.get("Contents", [])
        )

    def list_dirs(self, prefix: str) -> list[str]:
        if not prefix.endswith("/"):
            raise ValueError("list_dirs prefix must end with '/'")
        return sorted(
            common["Prefix"][len(prefix) :].rstrip("/")
            for page in self._pages(Prefix=prefix, Delimiter="/")
            for common in page.get("CommonPrefixes", [])
        )


class R2ClientError(StoreError):
    """R2 answered a request with an error."""

    def __init__(self, message: str, *, code: str, status: int | None):
        super().__init__(message)
        self.code = code
        self.status = status
