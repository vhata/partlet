import { describe, expect, it } from "vitest";
import { attachment, looksLikeText, parseRange, rawType } from "../src/policy";

const bytes = (s: string) => new TextEncoder().encode(s);

describe("looksLikeText", () => {
  it("accepts UTF-8 without NUL", () => {
    expect(looksLikeText(bytes("héllo\n"), false)).toBe(true);
    expect(looksLikeText(new Uint8Array(0), false)).toBe(true);
  });
  it("rejects a NUL byte", () => {
    expect(looksLikeText(new Uint8Array([0x61, 0, 0x62]), false)).toBe(false);
  });
  it("rejects invalid UTF-8", () => {
    expect(looksLikeText(new Uint8Array([0x63, 0x61, 0x66, 0xe9]), false)).toBe(false);
  });
  it("allows a multi-byte character cut off at the end of a truncated prefix", () => {
    const cut = bytes("aé").subarray(0, 2); // 0x61 0xC3
    expect(looksLikeText(cut, true)).toBe(true);
    expect(looksLikeText(cut, false)).toBe(false);
  });
});

describe("rawType", () => {
  it.each([
    ["a/logo.png", "image/png"],
    ["LOGO.JPG", "image/jpeg"],
    ["x.jpeg", "image/jpeg"],
    ["x.gif", "image/gif"],
    ["x.webp", "image/webp"],
  ])("serves %s as %s inline", (path, type) => {
    expect(rawType(path, bytes("<html>"), false)).toEqual({ contentType: type, disposition: null });
  });

  it.each(["README.md", "Makefile", "src/evil.js", "style.css", ".gitignore"])(
    "serves text %s as text/plain",
    (path) => {
      expect(rawType(path, bytes("<script>alert(1)</script>"), false)).toEqual({
        contentType: "text/plain; charset=utf-8",
        disposition: null,
      });
    },
  );

  it.each(["index.html", "a/b.HTM", "x.xhtml", "logo.svg", "pom.xml", "page.mhtml"])(
    "downloads markup %s",
    (path) => {
      const name = path.slice(path.lastIndexOf("/") + 1);
      expect(rawType(path, bytes("<p>"), false)).toEqual({
        contentType: "application/octet-stream",
        disposition: `attachment; filename*=UTF-8''${encodeURIComponent(name)}`,
      });
    },
  );

  it("downloads binary content whatever the name", () => {
    expect(rawType("notes.txt", new Uint8Array([1, 0, 2]), false).contentType).toBe(
      "application/octet-stream",
    );
  });
});

describe("attachment", () => {
  it("encodes the file name for filename*", () => {
    expect(attachment("f #1?'(x).txt")).toBe(
      "attachment; filename*=UTF-8''f%20%231%3F%27%28x%29.txt",
    );
    expect(attachment("ünï.html")).toBe("attachment; filename*=UTF-8''%C3%BCn%C3%AF.html");
  });
});

describe("parseRange", () => {
  it.each([
    ["bytes=0-", 10, { offset: 0, length: 10 }],
    ["bytes=4-", 10, { offset: 4, length: 6 }],
    ["bytes=2-5", 10, { offset: 2, length: 4 }],
    ["bytes=2-99", 10, { offset: 2, length: 8 }],
    ["bytes=10-", 10, "unsatisfiable"],
    ["bytes=5-2", 10, null],
    ["bytes=-5", 10, null],
    ["bytes=0-1,4-5", 10, null],
    ["items=0-1", 10, null],
    ["bytes=9007199254740993-", 10, null],
    ["bytes=0-9007199254740993", 10, null],
    ["bytes=0-", 0, "unsatisfiable"],
  ])("%s of %i bytes", (header, size, expected) => {
    expect(parseRange(header, size)).toEqual(expected);
  });
});
