import { env, exports } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";
import worker from "../src/index";
import { parseRoute } from "../src/route";
import { put, seedSite } from "./site";

const ORIGIN = "https://partlet.test";
const DIGEST = "a".repeat(64);
const BASE = `/_partlet/themes/${DIGEST}`;
const CSS = "body { color: #123456; }\n";
const IMAGE = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0, 1]);
const FORMATS = [
  ["png", "image/png"],
  ["jpg", "image/jpeg"],
  ["jpeg", "image/jpeg"],
  ["gif", "image/gif"],
  ["webp", "image/webp"],
] as const;
const get = (path: string, init: RequestInit = {}) =>
  exports.default.fetch(new Request(`${ORIGIN}${path}`, init));

const INVALID_PATHS = [
  "/_partlet/themes",
  "/_partlet/themes/",
  `/_partlet/themes/${"a".repeat(63)}/style.css`,
  `/_partlet/themes/${"a".repeat(65)}/style.css`,
  `/_partlet/themes/${DIGEST.toUpperCase()}/style.css`,
  `/_partlet/themes/${DIGEST}%0a/style.css`,
  `${BASE}/`,
  `${BASE}/style.css/`,
  `${BASE}/style.css/extra`,
  `${BASE}/other.css`,
  `${BASE}/theme.toml`,
  `${BASE}/LICENSE`,
  `${BASE}/index.html`,
  `${BASE}/assets`,
  `${BASE}/assets/`,
  `${BASE}/assets//image.png`,
  `${BASE}/assets/image.png/`,
  `${BASE}/assets/.private.png`,
  `${BASE}/assets/dir/.private.png`,
  `${BASE}/assets/dir%2Fimage.png`,
  `${BASE}/assets/%2e%2e%2fsecret.png`,
  `${BASE}/assets/a%5Cb.png`,
  `${BASE}/assets/sp%20ace.png`,
  `${BASE}/assets/%C3%A9.png`,
  `${BASE}/assets/a%00.png`,
  `${BASE}/assets/a%0A.png`,
  `${BASE}/assets/%FF.png`,
  `${BASE}/assets/a%.png`,
  `${BASE}/assets/a%252F.png`,
  `${BASE}/assets/stylesheet.css`,
  `${BASE}/assets/image.PNG`,
  `${BASE}/assets/image.svg`,
  `${BASE}/assets/image.svgz`,
  `${BASE}/assets/font.woff2`,
  `${BASE}/assets/file.js`,
  `${BASE}/assets/file.html`,
  `${BASE}/assets/image.png.html`,
  `${BASE}/assets/secret.txt`,
  `${BASE}/assets/png`,
  `${BASE}/assets/image.constructor`,
  `${BASE}/assets/image.__proto__`,
];

beforeAll(async () => {
  await seedSite();
  await put(`static/themes/${DIGEST}/style.css`, CSS);
  for (const [extension] of FORMATS) {
    await put(`static/themes/${DIGEST}/assets/Icons_1/logo-2.${extension}`, IMAGE);
  }
});

describe("theme route boundaries", () => {
  it("maps the stylesheet and nested raster assets", () => {
    expect(parseRoute(`${BASE}/style.css`)).toEqual({
      kind: "theme",
      digest: DIGEST,
      path: "style.css",
      format: "css",
    });
    expect(parseRoute(`${BASE}/assets/Icons_1/logo-2.png`)).toEqual({
      kind: "theme",
      digest: DIGEST,
      path: "assets/Icons_1/logo-2.png",
      format: "png",
    });
  });

  it.each(INVALID_PATHS)("rejects %s without reading storage", async (path) => {
    expect(parseRoute(path)).toBeNull();
    let reads = 0;
    const trap = () => {
      reads++;
      throw new Error("unexpected storage access");
    };
    const bucket = { get: trap, head: trap } as unknown as R2Bucket;
    const response = await worker.fetch(new Request(`${ORIGIN}${path}`), {
      ...env,
      BUCKET: bucket,
    });
    expect(response.status).toBe(404);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(reads).toBe(0);
    await response.arrayBuffer();
  });

  it.each([".", "..", "%2e", "%2e%2e"])("rejects dot segment %s", (segment) => {
    // Request URLs normalize dot segments before the Worker receives them;
    // exercise the parser directly with the otherwise unobservable input.
    expect(parseRoute(`${BASE}/assets/${segment}/image.png`)).toBeNull();
  });

  it("reads exactly the source-scoped asset key without project or theme metadata", async () => {
    const keys: string[] = [];
    const bucket = {
      get: (key: string) => {
        keys.push(key);
        return env.BUCKET.get(key);
      },
    } as unknown as R2Bucket;
    const response = await worker.fetch(new Request(`${ORIGIN}${BASE}/style.css`), {
      ...env,
      BUCKET: bucket,
    });
    expect(await response.text()).toBe(CSS);
    expect(keys).toEqual([`test/static/themes/${DIGEST}/style.css`]);
  });
});

describe("immutable theme responses", () => {
  it.each([
    ["style.css", "text/css; charset=utf-8"],
    ...FORMATS.map(([extension, type]) => [`assets/Icons_1/logo-2.${extension}`, type]),
  ])("serves %s with fixed MIME, CSP, cache and HEAD headers", async (path, type) => {
    const response = await get(`${BASE}/${path}`);
    const head = await get(`${BASE}/${path}`, { method: "HEAD" });
    expect(response.status).toBe(200);
    expect(head.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe(type);
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(response.headers.get("Content-Security-Policy")).toBe(
      "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    );
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(response.headers.get("ETag")).toMatch(/^"[0-9a-f]+"$/);
    const body = new Uint8Array(await response.arrayBuffer());
    expect(body).toEqual(path === "style.css" ? new TextEncoder().encode(CSS) : IMAGE);
    expect(response.headers.get("Content-Length")).toBe(String(body.length));
    for (const header of [
      "Content-Type",
      "Content-Length",
      "ETag",
      "Cache-Control",
      "Content-Security-Policy",
      "X-Content-Type-Options",
    ]) {
      expect(head.headers.get(header), header).toBe(response.headers.get(header));
    }
    expect(await head.text()).toBe("");
  });

  it.each(["GET", "HEAD"])("honors weak If-None-Match for %s", async (method) => {
    const first = await get(`${BASE}/style.css`);
    const etag = first.headers.get("ETag");
    await first.arrayBuffer();
    const response = await get(`${BASE}/style.css`, {
      method,
      headers: { "If-None-Match": `"other", W/${etag}` },
    });
    expect(response.status).toBe(304);
    expect(response.headers.get("ETag")).toBe(etag);
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(response.headers.get("Content-Security-Policy")).toContain("sandbox");
    expect(await response.text()).toBe("");
  });

  it("rejects an unmet If-Match before considering If-None-Match", async () => {
    const response = await get(`${BASE}/style.css`, {
      headers: { "If-Match": '"other"', "If-None-Match": "*" },
    });
    expect(response.status).toBe(412);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    await response.arrayBuffer();
  });

  it("uses the digest to select old and new resources independently", async () => {
    const next = "b".repeat(64);
    await put(`static/themes/${next}/style.css`, "new theme");
    expect(await (await get(`/_partlet/themes/${next}/style.css`)).text()).toBe("new theme");
    expect(await (await get(`${BASE}/style.css`)).text()).toBe(CSS);
  });

  it("ignores stored HTTP metadata", async () => {
    await env.BUCKET.put(`test/static/themes/${DIGEST}/assets/deceptive.png`, IMAGE, {
      httpMetadata: { contentType: "text/html", cacheControl: "no-store" },
    });
    const response = await get(`${BASE}/assets/deceptive.png`);
    expect(response.headers.get("Content-Type")).toBe("image/png");
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(response.headers.get("Content-Security-Policy")).toContain("sandbox");
    await response.arrayBuffer();
  });

  it("does not cache absent resources or answer wildcard validators with 304", async () => {
    const response = await get(`${BASE}/assets/missing.png`, {
      headers: { "If-None-Match": "*" },
    });
    expect(response.status).toBe(404);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(await response.text()).toContain('href="/_partlet/style.css"');
  });

  it("preserves the legacy stylesheet and page CSP", async () => {
    const legacy = await get("/_partlet/style.css");
    expect(await legacy.text()).toBe("body{}\n");
    expect(legacy.headers.get("Cache-Control")).toBe("public, max-age=60");
    const page = await get("/");
    expect(page.headers.get("Content-Security-Policy")).toBe(
      "default-src 'none'; style-src 'self'; img-src 'self' https:; " +
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    );
    await page.arrayBuffer();
  });
});
