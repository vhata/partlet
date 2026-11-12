"""Root-relative URLs for project pages, served by the Worker."""

from urllib.parse import quote


def tree_url(project: str, directory: str) -> str:
    return f"/{project}" if not directory else f"/{project}/tree/{quote(directory)}"


def blob_url(project: str, path: str) -> str:
    return f"/{project}/blob/{quote(path)}"


def raw_url(project: str, path: str) -> str:
    return f"/{project}/raw/{quote(path)}"


def archive_url(project: str, fmt: str) -> str:
    return f"/{project}/archive/{project}.{fmt}"


def clone_url(base_url: str, project: str) -> str:
    """Build a public clone URL without credentials or active URL schemes."""
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(c.isspace() or ord(c) < 32 or c == "\\" for c in base_url)
    ):
        raise ValueError(
            "base_url must be a public HTTP(S) URL without credentials, query or fragment"
        )
    return base_url.rstrip("/") + tree_url(project, "")
