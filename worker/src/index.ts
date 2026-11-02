// Partlet Worker: serve one source's published projects from R2.
//
// Read-only by construction: the bucket binding is only read (get and head),
// there are no write paths, and the Worker holds no other credentials. All
// rendering happens in the publisher; this file maps URLs to stored objects
// and chooses the response headers.

import {
  ARCHIVE_TYPES,
  attachment,
  baseHeaders,
  CACHE_IMMUTABLE,
  CACHE_NONE,
  CACHE_REVALIDATE,
  CSS,
  FILE_CSP,
  GIT_TYPES,
  HTML,
  JSON_TYPE,
  PAGE_CSP,
  parseRange,
  rawType,
  SNIFF_BYTES,
  TEXT,
} from "./policy";
import { NAME_RE, parseRoute, type Route } from "./route";

const BUILD_RE = /^[0-9a-f]{16}(?![\s\S])/;
const TIP_RE = /^(?:[0-9a-f]{40}|[0-9a-f]{64})(?![\s\S])/;

class Unreadable extends Error {}

interface Current {
  build: string;
  tip: string;
}

const NOT_FOUND_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found</title>
<link rel="stylesheet" href="/_partlet/style.css">
</head>
<body>
<header class="top"><a href="/">Partlet</a></header>
<main>
<h1>Not found</h1>
<p>There is no project or file at this address.</p>
</main>
</body>
</html>
`;

function notFound(request: Request): Response {
  const headers = baseHeaders(HTML, PAGE_CSP, CACHE_NONE);
  headers.set("Content-Length", String(new TextEncoder().encode(NOT_FOUND_HTML).length));
  return new Response(request.method === "HEAD" ? null : NOT_FOUND_HTML, { status: 404, headers });
}

function plain(
  request: Request,
  status: number,
  message: string,
  extra: Record<string, string> = {},
): Response {
  const headers = baseHeaders(TEXT, FILE_CSP, CACHE_NONE);
  headers.set("Content-Length", String(new TextEncoder().encode(`${message}\n`).length));
  for (const [name, value] of Object.entries(extra)) headers.set(name, value);
  return new Response(request.method === "HEAD" ? null : `${message}\n`, { status, headers });
}

// The project's `current` file names its live site build and tip. Both are
// checked before they go into a key, so a damaged file cannot point outside
// the project's prefix.
async function readCurrent(env: Env, project: string): Promise<Current | null> {
  const object = await env.BUCKET.get(`${env.SOURCE}/p/${project}/current`);
  if (object === null) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(await object.text());
  } catch {
    throw new Unreadable(`p/${project}/current is not JSON`);
  }
  const { build, tip } = (parsed ?? {}) as Record<string, unknown>;
  if (typeof build !== "string" || !BUILD_RE.test(build)) {
    throw new Unreadable(`p/${project}/current has no valid build`);
  }
  if (typeof tip !== "string" || !TIP_RE.test(tip)) {
    throw new Unreadable(`p/${project}/current has no valid tip`);
  }
  return { build, tip };
}

// GET/HEAD use weak comparison, including lists and *. Compare here rather
// than mapping every bodiless R2 conditional result to an HTTP 304.
function notModified(request: Request, etag: string): boolean {
  const value = request.headers.get("If-None-Match");
  return (
    value?.trim() === "*" ||
    (value?.split(",").some((tag) => tag.trim().replace(/^W\//, "") === etag) ?? false)
  );
}

function conditional(request: Request, etag: string, headers: Headers): Response | null {
  const match = request.headers.get("If-Match");
  // If-Match requires strong comparison and precedes If-None-Match.
  if (
    match !== null &&
    match.trim() !== "*" &&
    !match.split(",").some((tag) => tag.trim() === etag)
  ) {
    return plain(request, 412, "Precondition failed");
  }
  return notModified(request, etag) ? new Response(null, { status: 304, headers }) : null;
}

function reply(request: Request, body: ReadableStream | null, status: number, headers: Headers) {
  if (request.method === "HEAD") void body?.cancel();
  return new Response(request.method === "HEAD" ? null : body, { status, headers });
}

// Serve one stored object, honouring If-None-Match.
async function serveObject(
  request: Request,
  env: Env,
  key: string,
  headers: Headers,
): Promise<Response> {
  const object = await env.BUCKET.get(key);
  if (object === null) return notFound(request);
  headers.set("ETag", object.httpEtag);
  const precondition = conditional(request, object.httpEtag, headers);
  if (precondition !== null) {
    void object.body.cancel();
    return precondition;
  }
  headers.set("Content-Length", String(object.size));
  return reply(request, object.body, 200, headers);
}

// Evaluate validators before Range. If-Range needs a matching strong ETag;
// dates are ignored because this endpoint sends no Last-Modified validator.
async function servePack(
  request: Request,
  env: Env,
  key: string,
  headers: Headers,
): Promise<Response> {
  headers.set("Accept-Ranges", "bytes");
  const header = request.method === "GET" ? request.headers.get("Range") : null;
  if (header === null) return serveObject(request, env, key, headers);
  const head = await env.BUCKET.head(key);
  if (head === null) return notFound(request);
  headers.set("ETag", head.httpEtag);
  const precondition = conditional(request, head.httpEtag, headers);
  if (precondition !== null) return precondition;
  const ifRange = request.headers.get("If-Range");
  if (ifRange !== null && ifRange !== head.httpEtag) return serveObject(request, env, key, headers);
  const range = parseRange(header, head.size);
  if (range === null) return serveObject(request, env, key, headers);
  if (range === "unsatisfiable") {
    return plain(request, 416, "Range not satisfiable", {
      "Content-Range": `bytes */${head.size}`,
    });
  }
  const object = await env.BUCKET.get(key, { range });
  if (object === null || !("body" in object)) return notFound(request);
  const last = range.offset + range.length - 1;
  headers.set("ETag", object.httpEtag);
  headers.set("Content-Range", `bytes ${range.offset}-${last}/${object.size}`);
  headers.set("Content-Length", String(range.length));
  return reply(request, object.body, 206, headers);
}

// Raw files: the content type depends on the first bytes, so read those with
// a ranged get before serving the object.
async function serveRaw(request: Request, env: Env, key: string, path: string): Promise<Response> {
  const head = await env.BUCKET.head(key);
  if (head === null) return notFound(request);
  let prefix = new Uint8Array(0);
  if (head.size > 0) {
    const length = Math.min(head.size, SNIFF_BYTES);
    const probe = await env.BUCKET.get(key, { range: { offset: 0, length } });
    if (probe === null) return notFound(request);
    prefix = new Uint8Array(await probe.arrayBuffer());
  }
  const type = rawType(path, prefix, head.size > SNIFF_BYTES);
  const headers = baseHeaders(type.contentType, FILE_CSP, CACHE_REVALIDATE);
  if (type.disposition !== null) headers.set("Content-Disposition", type.disposition);
  return serveObject(request, env, key, headers);
}

async function serveProjectFile(
  request: Request,
  env: Env,
  route: Extract<Route, { kind: "page" | "raw" | "archive" }>,
): Promise<Response> {
  const current = await readCurrent(env, route.project);
  if (current === null) return notFound(request);
  const prefix = `${env.SOURCE}/p/${route.project}`;
  const site = `${prefix}/site/${current.build}`;
  switch (route.kind) {
    case "page":
      return serveObject(
        request,
        env,
        `${site}/${route.key}`,
        baseHeaders(HTML, PAGE_CSP, CACHE_REVALIDATE),
      );
    case "raw":
      return serveRaw(request, env, `${site}/${route.key}`, route.path);
    case "archive": {
      const headers = baseHeaders(ARCHIVE_TYPES[route.format], FILE_CSP, CACHE_REVALIDATE);
      headers.set("Content-Disposition", attachment(`${route.project}.${route.format}`));
      return serveObject(request, env, `${prefix}/archive/${current.tip}.${route.format}`, headers);
    }
  }
}

async function handle(request: Request, env: Env, route: Route): Promise<Response> {
  const source = env.SOURCE;
  switch (route.kind) {
    case "index":
      return serveObject(
        request,
        env,
        `${source}/index.html`,
        baseHeaders(HTML, PAGE_CSP, CACHE_REVALIDATE),
      );
    case "asset":
      return route.asset === "style.css"
        ? serveObject(
            request,
            env,
            `${source}/static/style.css`,
            baseHeaders(CSS, FILE_CSP, CACHE_REVALIDATE),
          )
        : serveObject(
            request,
            env,
            `${source}/index.json`,
            baseHeaders(JSON_TYPE, FILE_CSP, CACHE_REVALIDATE),
          );
    case "git": {
      const key = `${source}/p/${route.project}/git/${route.path}`;
      if (route.path === "info/refs") {
        const service = new URL(request.url).searchParams.get("service");
        if (service === "git-receive-pack")
          return plain(request, 403, "This repository is read-only.");
      }
      if (route.immutable) {
        const type = route.path.endsWith(".pack") ? GIT_TYPES.pack : GIT_TYPES.idx;
        return servePack(request, env, key, baseHeaders(type, FILE_CSP, CACHE_IMMUTABLE));
      }
      // Independent freshness of refs and pack lists can pair a new tip
      // with an old list that lacks its objects. Always read mutable Git
      // metadata fresh; pack retention separately protects in-flight reads.
      return serveObject(request, env, key, baseHeaders(TEXT, FILE_CSP, CACHE_NONE));
    }
    default:
      return serveProjectFile(request, env, route);
  }
}

export default {
  async fetch(request, env): Promise<Response> {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return plain(request, 405, "Method not allowed", { Allow: "GET, HEAD" });
    }
    if (typeof env.SOURCE !== "string" || !NAME_RE.test(env.SOURCE)) {
      return plain(request, 500, "This site is not configured.");
    }
    const route = parseRoute(new URL(request.url).pathname);
    if (route === null) return notFound(request);
    try {
      return await handle(request, env, route);
    } catch {
      // Bucket errors can include keys or provider details; never return or
      // log them to public clients. All failures are non-cacheable.
      return plain(request, 500, "Published content is temporarily unavailable.");
    }
  },
} satisfies ExportedHandler<Env>;
