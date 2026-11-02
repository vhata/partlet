import { env, exports } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";
import worker from "../src/index";
import { parseRoute } from "../src/route";
import { BUILD, PACK, put, seedSite, TIP } from "./site";

const ORIGIN = "https://partlet.test";
const text = async (res: Response) => new TextDecoder().decode(await res.arrayBuffer());
const get = (path: string, init: RequestInit = {}) =>
  exports.default.fetch(new Request(`${ORIGIN}${path}`, init));

beforeAll(seedSite);

describe("request and storage boundaries", () => {
  it.each([
    "/foo/raw/%2E",
    "/foo/raw/%2E%2E",
    "/foo/raw/%2Fsecret",
    "/foo/raw/%00",
    "/foo/raw/%FE",
    "/foo/raw/%",
    "/foo/raw/%C0%AF",
    "/foo/raw/%ED%A0%80",
    "/foo/tree/a//b",
    "/foo/tree/a//",
    "/foo/HEAD/",
    "/foo/info/refs/",
    "/foo/archive/foo.zip/",
    "/foo/locks/publish",
    "/foo/cleanup.json",
    "/foo/objects/info/http-alternates",
    "/foo/git/config",
    "/foo.git.git/HEAD",
    "/foo%0A",
    `/foo/objects/pack/${PACK}.pack%0A`,
  ])("rejects %s in the router", (path) => {
    expect(parseRoute(path)).toBeNull();
  });

  it("decodes exactly once and preserves Unicode identity", () => {
    expect(parseRoute("/foo/raw/a%252Fb")).toMatchObject({ path: "a%2Fb" });
    expect(parseRoute("/foo/raw/%C3%A9")).toMatchObject({ path: "é" });
    expect(parseRoute("/foo/raw/e%CC%81")).toMatchObject({ path: "e\u0301" });
  });

  it.each(["/foo/current", "/foo/config", "/foo/raw/%FF", "/foo/raw/a%2Fb"])(
    "does not read the bucket for invalid route %s",
    async (path) => {
      let reads = 0;
      const bucket = {
        get: () => {
          reads++;
          throw new Error("unexpected read");
        },
        head: () => {
          reads++;
          throw new Error("unexpected read");
        },
      } as unknown as R2Bucket;
      const res = await worker.fetch(new Request(`${ORIGIN}${path}`), { ...env, BUCKET: bucket });
      expect(res.status).toBe(404);
      expect(reads).toBe(0);
    },
  );

  it.each([
    null,
    [],
    3,
    false,
    "str",
    {},
    { build: BUILD },
    { tip: TIP },
    { build: 12, tip: TIP },
    { build: BUILD, tip: [TIP] },
    { build: `${BUILD}a`, tip: TIP },
    { build: BUILD.toUpperCase(), tip: TIP },
    { build: BUILD, tip: "a".repeat(41) },
    { build: BUILD, tip: "A".repeat(40) },
    { build: `${BUILD}\n`, tip: TIP },
    { build: BUILD, tip: `${TIP}\n` },
  ])("fails closed on malformed current %j", async (record) => {
    await put("p/malformed/current", JSON.stringify(record));
    const res = await get("/malformed");
    expect(res.status).toBe(500);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(await text(res)).not.toContain("test/p/");
  });

  it("accepts 64-hex tips and ignores additional current fields", async () => {
    await put(
      "p/sha256/current",
      JSON.stringify({
        build: BUILD,
        tip: "b".repeat(64),
        previous: { build: "../../secret" },
        credentials: "must never be exposed",
      }),
    );
    await put(`p/sha256/site/${BUILD}/index.html`, "sha256 project");
    const res = await get("/sha256");
    expect(res.status).toBe(200);
    expect(await text(res)).toBe("sha256 project");
  });
});

describe("conditional and range responses", () => {
  it.each(["exact", "list", "wildcard"])("accepts matching %s If-Match", async (kind) => {
    const first = await get("/foo");
    const etag = first.headers.get("ETag");
    await first.arrayBuffer();
    const value = kind === "exact" ? (etag ?? "") : kind === "list" ? `"other", ${etag}` : "*";
    const res = await get("/foo", { headers: { "If-Match": value } });
    expect(res.status).toBe(200);
    await res.arrayBuffer();
  });

  it("fails weak If-Match even when its opaque tag matches", async () => {
    const first = await get("/foo");
    const etag = first.headers.get("ETag");
    await first.arrayBuffer();
    const res = await get("/foo", { headers: { "If-Match": `W/${etag}`, "If-None-Match": "*" } });
    expect(res.status).toBe(412);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it.each(["weak", "list", "wildcard"])("matches %s If-None-Match", async (kind) => {
    const first = await get("/foo");
    const etag = first.headers.get("ETag");
    expect(etag).toBeTruthy();
    await first.arrayBuffer();
    const header = kind === "weak" ? `W/${etag}` : kind === "list" ? `"other", W/${etag}` : "*";
    const res = await get("/foo", { headers: { "If-None-Match": header } });
    expect(res.status).toBe(304);
    expect(res.headers.get("ETag")).toBe(etag);
    expect(await text(res)).toBe("");
  });

  it("does not turn a missing object into a 304 for wildcard", async () => {
    const res = await get("/foo/raw/missing", { headers: { "If-None-Match": "*" } });
    expect(res.status).toBe(404);
  });

  it("revalidates against the object selected by the latest current", async () => {
    const nextBuild = "d".repeat(16);
    await put("p/conditional/current", JSON.stringify({ build: BUILD, tip: TIP }));
    await put(`p/conditional/site/${BUILD}/index.html`, "old");
    const old = await get("/conditional");
    const oldEtag = old.headers.get("ETag") ?? "";
    await old.arrayBuffer();
    await put(`p/conditional/site/${nextBuild}/index.html`, "new");
    await put("p/conditional/current", JSON.stringify({ build: nextBuild, tip: TIP }));
    const res = await get("/conditional", { headers: { "If-None-Match": oldEtag } });
    expect(res.status).toBe(200);
    expect(await text(res)).toBe("new");
  });

  it.each(['"other"', 'W/"other"', "Thu, 01 Jan 1970 00:00:00 GMT"])(
    "ignores Range for unmatched or unsupported If-Range %s",
    async (ifRange) => {
      const res = await get(`/foo/objects/pack/${PACK}.pack`, {
        headers: { Range: "bytes=5-", "If-Range": ifRange },
      });
      expect(res.status).toBe(200);
      expect(await text(res)).toBe("PACK-bytes-0123456789");
    },
  );

  it("accepts a strong matching If-Range", async () => {
    const first = await get(`/foo/objects/pack/${PACK}.pack`);
    const etag = first.headers.get("ETag") ?? "";
    await first.arrayBuffer();
    const res = await get(`/foo/objects/pack/${PACK}.pack`, {
      headers: { Range: "bytes=0-3", "If-Range": etag },
    });
    expect(res.status).toBe(206);
    expect(await text(res)).toBe("PACK");
  });

  it("a matching validator takes precedence over a range", async () => {
    const first = await get(`/foo/objects/pack/${PACK}.pack`);
    const etag = first.headers.get("ETag") ?? "";
    await first.arrayBuffer();
    const res = await get(`/foo/objects/pack/${PACK}.pack`, {
      headers: { Range: "bytes=999-", "If-None-Match": etag },
    });
    expect(res.status).toBe(304);
    expect(res.headers.get("Content-Range")).toBeNull();
  });

  it("ignores Range for HEAD", async () => {
    const res = await get(`/foo/objects/pack/${PACK}.pack`, {
      method: "HEAD",
      headers: { Range: "bytes=0-3" },
    });
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Length")).toBe("21");
    expect(res.headers.get("Content-Range")).toBeNull();
    expect(await text(res)).toBe("");
  });

  it("ignores ranges on non-pack routes", async () => {
    const res = await get("/foo/raw/README.md", { headers: { Range: "bytes=0-1" } });
    expect(res.status).toBe(200);
    expect(await text(res)).toBe("# Foo\n");
  });
});

describe("content safety and error policy", () => {
  it.each(["constructor", "__proto__", "toString"])(
    "serves inherited object-property extension %s as text",
    async (extension) => {
      const path = `a.${extension}`;
      await put(`p/foo/site/${BUILD}/raw/${path}`, "safe text");
      const res = await get(`/foo/raw/${path}`);
      expect(res.status).toBe(200);
      expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
      await res.arrayBuffer();
    },
  );

  it("rejects SOURCE with a trailing newline before bucket access", async () => {
    let reads = 0;
    const bucket = {
      get: () => {
        reads++;
        throw new Error("unexpected read");
      },
    } as unknown as R2Bucket;
    const res = await worker.fetch(new Request(`${ORIGIN}/foo`), {
      ...env,
      SOURCE: "test\n",
      BUCKET: bucket,
    });
    expect(res.status).toBe(500);
    expect(reads).toBe(0);
  });

  it("disregards stored active content and other HTTP metadata", async () => {
    await env.BUCKET.put(`test/p/foo/site/${BUILD}/raw/deceptive.txt`, "<script>evil()</script>", {
      httpMetadata: {
        contentType: "text/html",
        contentDisposition: "inline",
        cacheControl: "public, immutable",
      },
    });
    const res = await get("/foo/raw/deceptive.txt");
    expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect(res.headers.get("Content-Disposition")).toBeNull();
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(res.headers.get("Content-Security-Policy")).toContain("sandbox");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    await res.arrayBuffer();
  });

  it("sandboxes HTML disguised with an image extension", async () => {
    await put(`p/foo/site/${BUILD}/raw/deceptive.png`, "<script>evil()</script>");
    const res = await get("/foo/raw/deceptive.png");
    expect(res.headers.get("Content-Type")).toBe("image/png");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'none'");
    expect(res.headers.get("Content-Security-Policy")).toContain("sandbox");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    await res.arrayBuffer();
  });

  it.each([
    "/",
    "/_partlet/style.css",
    "/_partlet/index.json",
    "/foo",
    "/foo/tree/docs",
    "/foo/blob/README.md",
    "/foo/raw/README.md",
    "/foo/archive/foo.zip",
    "/foo/HEAD",
    "/foo/info/refs",
    "/foo/objects/info/packs",
    `/foo/objects/pack/${PACK}.idx`,
  ])("HEAD %s preserves GET status and representation headers", async (path) => {
    const full = await get(path);
    const head = await get(path, { method: "HEAD" });
    expect(head.status).toBe(full.status);
    for (const header of [
      "Content-Type",
      "Content-Length",
      "Content-Disposition",
      "ETag",
      "Cache-Control",
      "Content-Security-Policy",
      "X-Content-Type-Options",
    ]) {
      expect(head.headers.get(header), header).toBe(full.headers.get(header));
    }
    await full.arrayBuffer();
    expect(await text(head)).toBe("");
  });

  it("missing immutable packs are never cached", async () => {
    const res = await get(`/foo/objects/pack/pack-${"0".repeat(40)}.pack`);
    expect(res.status).toBe(404);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("read failures return a generic non-cacheable response", async () => {
    const bucket = {
      get: () => {
        throw new Error("secret bucket and credential");
      },
    } as unknown as R2Bucket;
    const res = await worker.fetch(new Request(`${ORIGIN}/foo`), { ...env, BUCKET: bucket });
    expect(res.status).toBe(500);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(await text(res)).not.toContain("secret");
  });
});

describe("cache and out-of-policy deletion boundary", () => {
  it("an explicitly deleted advertised pack returns an uncached 404", async () => {
    const project = "grace";
    const firstPack = `pack-${"1".repeat(40)}`;
    const secondPack = `pack-${"2".repeat(40)}`;
    const thirdPack = `pack-${"3".repeat(40)}`;
    await put(`p/${project}/git/objects/pack/${firstPack}.pack`, "first pack");
    await put(`p/${project}/git/objects/info/packs`, `P ${firstPack}.pack\n\n`);
    const metadata = await get(`/${project}/objects/info/packs`);
    expect(metadata.headers.get("Cache-Control")).toBe("public, max-age=60");
    const cachedList = await text(metadata);

    // Reproduce the historical one-publication-only policy by deleting A
    // explicitly while metadata is still fresh. The publisher now retains
    // retired packs for an hour; tests/e2e/test_wrangler.py exercises that
    // protection through actual publication and public Worker object URLs.
    // The Worker must still fail safely after out-of-policy deletion.
    await put(`p/${project}/git/objects/pack/${secondPack}.pack`, "second pack");
    await put(`p/${project}/git/objects/info/packs`, `P ${secondPack}.pack\n\n`);
    expect((await get(`/${project}/objects/pack/${firstPack}.pack`)).status).toBe(200);
    await put(`p/${project}/git/objects/pack/${thirdPack}.pack`, "third pack");
    await put(`p/${project}/git/objects/info/packs`, `P ${thirdPack}.pack\n\n`);
    await env.BUCKET.delete(`test/p/${project}/git/objects/pack/${firstPack}.pack`);

    expect(cachedList).toContain(`${firstPack}.pack`);
    const missing = await get(`/${project}/objects/pack/${firstPack}.pack`);
    expect(missing.status).toBe(404);
    expect(missing.headers.get("Cache-Control")).toBe("no-store");
    const latest = await get(`/${project}/objects/info/packs`);
    expect(await text(latest)).toContain(`${thirdPack}.pack`);
  });
});
