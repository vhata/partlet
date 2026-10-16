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
