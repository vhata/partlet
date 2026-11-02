// Map a request path to what it names in the store. Pure: no I/O.
//
// Every route this returns is safe to turn into a store key: project names
// match the manifest's name rule, file paths are decoded segment by segment
// and never contain "", ".", "..", "/" or NUL, and Git paths come from a
// fixed list. Anything else is null, which the Worker answers with a 404
// without reading the bucket.

export const NAME_RE = /^[a-z0-9][a-z0-9._-]*(?![\s\S])/;
const PACK_RE = /^pack-(?:[0-9a-f]{40}|[0-9a-f]{64})\.(?:pack|idx)(?![\s\S])/;

// Keys under a project's live site build, as the publisher writes them
// (src/partlet/site/render.py). The Worker builds them here and nowhere else,
// so a change to the publisher's layout is one edit in this file.
export const SITE_KEYS = {
  project: "index.html",
  tree: (dir: string) => `tree/${dir.split("/").join("/children/")}/index.html`,
  blob: (path: string) => `blob/${path}`,
  raw: (path: string) => `raw/${path}`,
};

export const ARCHIVE_FORMATS = ["tar.gz", "zip"] as const;
export type ArchiveFormat = (typeof ARCHIVE_FORMATS)[number];

export type Route =
  | { kind: "index" }
  | { kind: "asset"; asset: "style.css" | "index.json" }
  // `key` is relative to the live site build (SITE_KEYS); `path` is the
  // file's path in the project.
  | { kind: "page"; project: string; key: string }
  | { kind: "raw"; project: string; path: string; key: string }
  | { kind: "archive"; project: string; format: ArchiveFormat }
  // `path` is the key under the project's git/ prefix.
  | { kind: "git"; project: string; path: string; immutable: boolean };

function decodeSegments(pathname: string): string[] | null {
  const segments: string[] = [];
  for (const raw of pathname.split("/").slice(1)) {
    let segment: string;
    try {
      segment = decodeURIComponent(raw);
    } catch {
      return null; // malformed escape or invalid UTF-8
    }
    if (segment === "." || segment === ".." || segment.includes("/") || segment.includes("\0")) {
      return null;
    }
    segments.push(segment);
  }
  return segments;
}

function filePath(segments: string[]): string | null {
  if (segments.length === 0 || segments.includes("")) return null;
  return segments.join("/");
}

function projectName(segment: string): string | null {
  const name = segment.endsWith(".git") ? segment.slice(0, -4) : segment;
  return NAME_RE.test(name) && !name.endsWith(".git") ? name : null;
}

function gitRoute(project: string, rest: string[]): Route | null {
  const path = rest.join("/");
  if (path === "HEAD" || path === "info/refs" || path === "objects/info/packs") {
    return { kind: "git", project, path, immutable: false };
  }
  if (
    rest.length === 3 &&
    rest[0] === "objects" &&
    rest[1] === "pack" &&
    PACK_RE.test(rest[2] ?? "")
  ) {
    return { kind: "git", project, path, immutable: true };
  }
  // Loose objects, alternates and anything else: the publisher writes only
  // packs, so these are always 404.
  return null;
}

export function parseRoute(pathname: string): Route | null {
  if (!pathname.startsWith("/")) return null;
  if (pathname === "/") return { kind: "index" };
  const segments = decodeSegments(pathname);
  if (segments === null) return null;

  const [first, ...rest] = segments;
  if (first === "_partlet") {
    if (rest.length === 1 && (rest[0] === "style.css" || rest[0] === "index.json")) {
      return { kind: "asset", asset: rest[0] };
    }
    return null;
  }
  const project = projectName(first ?? "");
  if (project === null) return null;

  // A single trailing slash is accepted on the project page and directory
  // listings only; a file path never ends in "/".
  const [section, ...tail] = rest;
  if (rest.length === 0 || (rest.length === 1 && section === "")) {
    return { kind: "page", project, key: SITE_KEYS.project };
  }
  if (section === "tree") {
    const dirs = tail.at(-1) === "" ? tail.slice(0, -1) : tail;
    if (dirs.length === 0) return { kind: "page", project, key: SITE_KEYS.project };
    const dir = filePath(dirs);
    return dir === null ? null : { kind: "page", project, key: SITE_KEYS.tree(dir) };
  }
  if (section === "blob" || section === "raw") {
    const path = filePath(tail);
    if (path === null) return null;
    return section === "blob"
      ? { kind: "page", project, key: SITE_KEYS.blob(path) }
      : { kind: "raw", project, path, key: SITE_KEYS.raw(path) };
  }
  if (section === "archive") {
    if (tail.length !== 1) return null;
    const format = ARCHIVE_FORMATS.find((f) => tail[0] === `${project}.${f}`);
    return format ? { kind: "archive", project, format } : null;
  }
  return gitRoute(project, rest);
}
