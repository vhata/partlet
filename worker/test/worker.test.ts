import { env, exports } from "cloudflare:workers";
import { beforeAll, describe, expect, it } from "vitest";
import worker from "../src/index";
import { BUILD, PACK, put, seedSite, TIP } from "./site";

const ORIGIN = "https://partlet.test";

function get(path: string, init: RequestInit = {}): Promise<Response> {
  return exports.default.fetch(new Request(`${ORIGIN}${path}`, init));
}

// Read a body as text without the runtime's warning for binary content types.
async function text(res: Response): Promise<string> {
  return new TextDecoder().decode(await res.arrayBuffer());
}

beforeAll(seedSite);

describe("pages", () => {
  it.each([
    ["/", "<p>site index</p>"],
    ["/foo", "<p>project foo</p>"],
    ["/foo/", "<p>project foo</p>"],
    ["/foo.git", "<p>project foo</p>"],
    ["/foo/tree/docs", "<p>tree docs</p>"],
    ["/foo/tree/docs/index.html", "<p>tree docs/index.html</p>"],
    ["/foo/blob/docs/index.html/leaf.txt", "<p>blob docs/index.html/leaf.txt</p>"],
    ["/foo/blob/a!'()*~.txt", "<p>blob a!'()*~.txt</p>"],
    ["/foo/blob/a%21%27%28%29%2A%7E.txt", "<p>blob a!'()*~.txt</p>"],
    ["/foo/tree/sp%20ace", "<p>tree sp ace</p>"],
    ["/foo/blob/README.md", "<p>blob README.md</p>"],
    ["/foo/blob/sp%20ace/f%20%231%3F.txt", "<p>blob sp ace/f #1?.txt</p>"],
    ["/foo/blob/%C3%BCn%C3%AF.txt", "<p>blob ünï.txt</p>"],
  ])("%s", async (path, body) => {
    const res = await get(path);
    expect(res.status).toBe(200);
    expect(await text(res)).toBe(body);
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'none'");
    expect(res.headers.get("Content-Security-Policy")).not.toContain("script-src");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("ETag")).toMatch(/^"[0-9a-f]+"$/);
  });

  it("serves the stylesheet and index.json", async () => {
    const css = await get("/_partlet/style.css");
    expect(css.headers.get("Content-Type")).toBe("text/css; charset=utf-8");
    expect(await text(css)).toBe("body{}\n");
    const json = await get("/_partlet/index.json");
    expect(json.headers.get("Content-Type")).toBe("application/json");
    expect(await text(json)).toBe("[]\n");
  });

  it("answers a matching If-None-Match with 304", async () => {
    const first = await get("/foo/blob/README.md");
    const etag = first.headers.get("ETag") ?? "";
    await first.arrayBuffer();
    const again = await get("/foo/blob/README.md", { headers: { "If-None-Match": etag } });
    expect(again.status).toBe(304);
    expect(again.headers.get("ETag")).toBe(etag);
    expect(again.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(await text(again)).toBe("");
  });

  it("answers a failed If-Match with 412 rather than 304", async () => {
    const res = await get("/foo/blob/README.md", {
      headers: { "If-Match": '"nope"', "If-Unmodified-Since": "Thu, 01 Jan 1970 00:00:00 GMT" },
    });
    expect(res.status).toBe(412);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it("follows current to a new build", async () => {
    const build = "00000000000000aa";
    await put("p/moved/current", JSON.stringify({ build: BUILD, tip: TIP }));
    await put(`p/moved/site/${BUILD}/index.html`, "old");
    await put(`p/moved/site/${build}/index.html`, "new");
    expect(await text(await get("/moved"))).toBe("old");
    await put("p/moved/current", JSON.stringify({ build, tip: TIP }));
    expect(await text(await get("/moved"))).toBe("new");
  });
});

describe("raw files", () => {
  it.each([
    ["/foo/raw/README.md", "text/plain; charset=utf-8", null],
    ["/foo/raw/evil.js", "text/plain; charset=utf-8", null],
    ["/foo/raw/empty", "text/plain; charset=utf-8", null],
    ["/foo/raw/img/logo.png", "image/png", null],
    ["/foo/raw/evil.html", "application/octet-stream", "attachment; filename*=UTF-8''evil.html"],
    ["/foo/raw/evil.svg", "application/octet-stream", "attachment; filename*=UTF-8''evil.svg"],
    ["/foo/raw/bin/data", "application/octet-stream", "attachment; filename*=UTF-8''data"],
    ["/foo/raw/latin1.txt", "application/octet-stream", "attachment; filename*=UTF-8''latin1.txt"],
    ["/foo/raw/sp%20ace/f%20%231%3F.txt", "text/plain; charset=utf-8", null],
    ["/foo/raw/docs/index.html/leaf.txt", "text/plain; charset=utf-8", null],
  ])("%s is %s", async (path, type, disposition) => {
    const res = await get(path);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe(type);
    expect(res.headers.get("Content-Disposition")).toBe(disposition);
    expect(res.headers.get("Content-Security-Policy")).toBe(
      "default-src 'none'; style-src 'unsafe-inline'; sandbox",
    );
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    await res.arrayBuffer();
  });

  it("returns the stored bytes unchanged", async () => {
    const res = await get("/foo/raw/latin1.txt");
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(
      new Uint8Array([0x63, 0x61, 0x66, 0xe9]),
    );
  });

  it("classifies a large text file whose first 8000 bytes end inside a character", async () => {
    // Byte 7999 is the first byte of a two-byte "é".
    await put(`p/foo/site/${BUILD}/raw/big.txt`, `a${"é".repeat(5000)}\n`); // 10002 bytes
    const res = await get("/foo/raw/big.txt");
    expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect((await res.arrayBuffer()).byteLength).toBe(10002);
  });
});

describe("archives", () => {
  it.each([
    ["tar.gz", "application/gzip", "TGZ"],
    ["zip", "application/zip", "ZIP"],
  ])("serves the latest %s", async (fmt, type, body) => {
    const res = await get(`/foo/archive/foo.${fmt}`);
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe(type);
    expect(res.headers.get("Content-Disposition")).toBe(`attachment; filename*=UTF-8''foo.${fmt}`);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=60");
    expect(await text(res)).toBe(body);
  });
});

describe("git dumb HTTP", () => {
  it("serves info/refs as plain text for a smart-protocol probe", async () => {
    const res = await get("/foo/info/refs?service=git-upload-pack");
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(await text(res)).toBe(`${TIP}\trefs/heads/main\n`);
  });

  it("serves the same files under the .git alias", async () => {
    expect(await text(await get("/foo.git/info/refs"))).toBe(`${TIP}\trefs/heads/main\n`);
    expect(await text(await get("/foo.git/HEAD"))).toBe("ref: refs/heads/main\n");
  });

  it("refuses push discovery", async () => {
    const res = await get("/foo/info/refs?service=git-receive-pack");
    expect(res.status).toBe(403);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it.each([
    ["/foo/HEAD", "ref: refs/heads/main\n"],
    ["/foo/objects/info/packs", `P ${PACK}.pack\n\n`],
  ])("serves %s without caching", async (path, body) => {
    const res = await get(path);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(res.headers.get("Content-Type")).toBe("text/plain; charset=utf-8");
    expect(await text(res)).toBe(body);
  });

  it.each([
    [`/foo/objects/pack/${PACK}.pack`, "application/x-git-packed-objects", "PACK-bytes-0123456789"],
    [`/foo/objects/pack/${PACK}.idx`, "application/x-git-packed-objects-toc", "IDX-bytes"],
  ])("serves %s as immutable", async (path, type, body) => {
    const res = await get(path);
    expect(res.headers.get("Content-Type")).toBe(type);
    expect(res.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(res.headers.get("Accept-Ranges")).toBe("bytes");
    expect(await text(res)).toBe(body);
  });

  it("answers a byte range on a pack", async () => {
    const res = await get(`/foo/objects/pack/${PACK}.pack`, { headers: { Range: "bytes=5-" } });
    expect(res.status).toBe(206);
    expect(res.headers.get("Content-Range")).toBe("bytes 5-20/21");
    expect(await text(res)).toBe("bytes-0123456789");
  });

  it("answers a bounded byte range on a pack", async () => {
    const res = await get(`/foo/objects/pack/${PACK}.pack`, { headers: { Range: "bytes=0-3" } });
    expect(res.status).toBe(206);
    expect(res.headers.get("Content-Range")).toBe("bytes 0-3/21");
    expect(await text(res)).toBe("PACK");
  });

  it("rejects a range past the end", async () => {
    const res = await get(`/foo/objects/pack/${PACK}.pack`, { headers: { Range: "bytes=21-" } });
    expect(res.status).toBe(416);
    expect(res.headers.get("Content-Range")).toBe("bytes */21");
  });

  it("ignores a range form it does not support", async () => {
    const res = await get(`/foo/objects/pack/${PACK}.pack`, { headers: { Range: "bytes=-5" } });
    expect(res.status).toBe(200);
    expect(await text(res)).toBe("PACK-bytes-0123456789");
  });
});

describe("HEAD requests", () => {
  // The runtime drops a HEAD response's body itself, so these check the
  // status, headers and Content-Length, not the empty body.
  it.each([
    ["/foo/HEAD", "text/plain; charset=utf-8", "21"],
    ["/foo/info/refs", "text/plain; charset=utf-8", "57"],
    [`/foo/objects/pack/${PACK}.pack`, "application/x-git-packed-objects", "21"],
    ["/foo/raw/img/logo.png", "image/png", "10"],
    ["/foo/blob/README.md", "text/html; charset=utf-8", "21"],
  ])("HEAD %s has the GET headers and length", async (path, type, length) => {
    const res = await get(path, { method: "HEAD" });
    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe(type);
    expect(res.headers.get("Content-Length")).toBe(length);
    expect(await text(res)).toBe("");
  });
});

describe("not found and errors", () => {
  it.each([
    "/nope",
    "/nope/info/refs",
    "/foo/blob/missing",
    "/foo/tree/README.md",
    "/foo/raw/missing",
    "/foo/raw/%2e%2e/%2e%2e/index.html",
    "/foo/objects/info/alternates",
    "/foo/current",
    "/foo/config",
    "/Foo",
    "/foo/archive/bar.zip",
  ])("%s is a 404 page", async (path) => {
    const res = await get(path);
    expect(res.status).toBe(404);
    expect(res.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    const html = await text(res);
    expect(html).toContain("Not found");
    expect(html).toContain('href="/">Home</a>');
  });

  it("cannot reach keys outside the project", async () => {
    await env.BUCKET.put("secret.txt", "outside the source prefix");
    await put("secret.txt", "outside any project");
    for (const path of [
      "/foo/raw/..%2F..%2F..%2F..%2F..%2Fsecret.txt",
      "/foo/raw/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/secret.txt",
      "/..%2Fsecret.txt",
      "/foo/..%2F..%2F..%2Fsecret.txt",
    ]) {
      const res = await get(path);
      expect(res.status, path).toBe(404);
      expect(await text(res)).not.toContain("outside");
    }
  });

  it("HEAD of a missing file is a 404", async () => {
    const res = await get("/foo/raw/missing", { method: "HEAD" });
    expect(res.status).toBe(404);
    expect(await text(res)).toBe("");
  });

  it.each(["POST", "PUT", "DELETE", "PROPFIND"])("%s is not allowed", async (method) => {
    const res = await get("/foo/info/refs", { method });
    expect(res.status).toBe(405);
    expect(res.headers.get("Allow")).toBe("GET, HEAD");
  });

  it.each([
    ["not json", "{"],
    ["a bad build id", JSON.stringify({ build: "../../x", tip: TIP })],
    ["a bad tip", JSON.stringify({ build: BUILD, tip: "../x" })],
  ])("a current file with %s is a 500", async (_label, body) => {
    await put("p/broken/current", body);
    const res = await get("/broken");
    expect(res.status).toBe(500);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  it.each(["", "Bad", "../x"])("SOURCE %j is a 500, not a read elsewhere", async (source) => {
    const res = await worker.fetch(new Request(`${ORIGIN}/foo`), { ...env, SOURCE: source });
    expect(res.status).toBe(500);
  });
});
