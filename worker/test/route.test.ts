import { describe, expect, it } from "vitest";
import { parseRoute } from "../src/route";

describe("parseRoute", () => {
  it.each([
    ["/", { kind: "index" }],
    ["/_partlet/style.css", { kind: "asset", asset: "style.css" }],
    ["/_partlet/index.json", { kind: "asset", asset: "index.json" }],
    ["/foo", { kind: "page", project: "foo", key: "index.html" }],
    ["/foo/", { kind: "page", project: "foo", key: "index.html" }],
    ["/foo.git", { kind: "page", project: "foo", key: "index.html" }],
    ["/foo/tree", { kind: "page", project: "foo", key: "index.html" }],
    ["/foo/tree/docs", { kind: "page", project: "foo", key: "tree/docs/index.html" }],
    ["/foo/tree/docs/", { kind: "page", project: "foo", key: "tree/docs/index.html" }],
    ["/foo/tree/sp%20ace", { kind: "page", project: "foo", key: "tree/sp ace/index.html" }],
    ["/foo/blob/README.md", { kind: "page", project: "foo", key: "blob/README.md" }],
    [
      "/foo/blob/sp%20ace/f%20%231%3F.txt",
      { kind: "page", project: "foo", key: "blob/sp ace/f #1?.txt" },
    ],
    ["/foo/blob/%C3%BCn%C3%AF.txt", { kind: "page", project: "foo", key: "blob/ünï.txt" }],
    ["/foo/blob/100%25", { kind: "page", project: "foo", key: "blob/100%" }],
    // Python's quote() escapes !'()* and encodeURIComponent does not; both decode alike.
    ["/foo/blob/a!'()*~.txt", { kind: "page", project: "foo", key: "blob/a!'()*~.txt" }],
    [
      "/foo/blob/a%21%27%28%29%2A%7E.txt",
      { kind: "page", project: "foo", key: "blob/a!'()*~.txt" },
    ],
    // Directory page files and child directories occupy separate namespaces.
    [
      "/foo/tree/docs/index.html",
      { kind: "page", project: "foo", key: "tree/docs/children/index.html/index.html" },
    ],
    [
      "/foo/tree/docs/children/index.html",
      {
        kind: "page",
        project: "foo",
        key: "tree/docs/children/children/children/index.html/index.html",
      },
    ],
    [
      "/foo/tree/docs/a%21%27%28%29%2A%7E%25%C3%A9",
      { kind: "page", project: "foo", key: "tree/docs/children/a!'()*~%é/index.html" },
    ],
    [
      "/foo/blob/docs/index.html/leaf.txt",
      { kind: "page", project: "foo", key: "blob/docs/index.html/leaf.txt" },
    ],
    [
      "/foo/raw/img/logo.png",
      { kind: "raw", project: "foo", path: "img/logo.png", key: "raw/img/logo.png" },
    ],
    ["/foo.git/raw/a", { kind: "raw", project: "foo", path: "a", key: "raw/a" }],
    ["/foo/archive/foo.tar.gz", { kind: "archive", project: "foo", format: "tar.gz" }],
    ["/foo/archive/foo.zip", { kind: "archive", project: "foo", format: "zip" }],
    ["/foo/HEAD", { kind: "git", project: "foo", path: "HEAD", immutable: false }],
    ["/foo/info/refs", { kind: "git", project: "foo", path: "info/refs", immutable: false }],
    ["/foo.git/info/refs", { kind: "git", project: "foo", path: "info/refs", immutable: false }],
    [
      "/foo/objects/info/packs",
      { kind: "git", project: "foo", path: "objects/info/packs", immutable: false },
    ],
    [
      `/foo/objects/pack/pack-${"a".repeat(40)}.pack`,
      {
        kind: "git",
        project: "foo",
        path: `objects/pack/pack-${"a".repeat(40)}.pack`,
        immutable: true,
      },
    ],
    [
      `/foo/objects/pack/pack-${"b".repeat(64)}.idx`,
      {
        kind: "git",
        project: "foo",
        path: `objects/pack/pack-${"b".repeat(64)}.idx`,
        immutable: true,
      },
    ],
  ])("%s", (path, expected) => {
    expect(parseRoute(path)).toEqual(expected);
  });

  it.each([
    "//",
    "/Foo",
    "/_foo",
    "/.git",
    "/foo.git.git",
    "/_partlet",
    "/_partlet/other",
    "/foo/blob",
    "/foo/blob/",
    "/foo/blob/a/",
    "/foo/blob/a//b",
    "/foo/raw/%2e%2e/secret",
    "/foo/raw/a%2Fb",
    "/foo/raw/a%00b",
    "/foo/raw/%E0%A4%A",
    "/foo/raw/%FF",
    "/foo/tree//docs",
    "/foo/archive/bar.zip",
    "/foo/archive/foo.tar",
    "/foo/archive/x/foo.zip",
    "/foo/info",
    "/foo/info/refs/x",
    "/foo/objects/info/alternates",
    "/foo/objects/info/http-alternates",
    `/foo/objects/ab/${"c".repeat(38)}`,
    "/foo/objects/pack/pack-abc.pack",
    `/foo/objects/pack/pack-${"A".repeat(40)}.pack`,
    `/foo/objects/pack/pack-${"a".repeat(40)}.keep`,
    "/foo/config",
    "/foo/current",
    "/foo/site/x",
    "/foo//",
  ])("%s is not a route", (path) => {
    expect(parseRoute(path)).toBeNull();
  });
});
