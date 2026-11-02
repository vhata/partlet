// Response headers: content types, caching and the security headers every
// response carries. Pure: no I/O.

// Packs are content-addressed and never rewritten.
export const CACHE_IMMUTABLE = "public, max-age=31536000, immutable";
// Site URLs, including pages, raw files and archives whose stored key is
// resolved through `current`. Mutable Git metadata instead uses CACHE_NONE.
export const CACHE_REVALIDATE = "public, max-age=60";
export const CACHE_NONE = "no-store";

// Rendered pages: the stylesheet and images only, never scripts, frames,
// forms or a <base> override. README images may be hosted elsewhere (https).
export const PAGE_CSP =
  "default-src 'none'; style-src 'self'; img-src 'self' https:; " +
  "base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
// Everything else (raw files, Git files, archives, JSON, errors): if a
// browser renders it as a document at all, it gets an opaque origin and no
// script, even when the content type below is wrong.
export const FILE_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox";

export const HTML = "text/html; charset=utf-8";
export const TEXT = "text/plain; charset=utf-8";
export const OCTET = "application/octet-stream";
export const CSS = "text/css; charset=utf-8";
export const JSON_TYPE = "application/json";

// The number of leading bytes a raw file is classified from; the same
// window git and the publisher's is_binary() use for the NUL check.
export const SNIFF_BYTES = 8000;

const IMAGE_TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
};

// Markup a browser would render as an active document if it ignored the
// content type: always a download, even though it is text.
const MARKUP_EXTENSIONS = new Set([
  "htm",
  "html",
  "shtml",
  "xht",
  "xhtml",
  "mht",
  "mhtml",
  "svg",
  "svgz",
  "xml",
  "xsl",
  "xslt",
]);

export const GIT_TYPES = {
  pack: "application/x-git-packed-objects",
  idx: "application/x-git-packed-objects-toc",
} as const;

export const ARCHIVE_TYPES = { "tar.gz": "application/gzip", zip: "application/zip" } as const;

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot + 1).toLowerCase();
}

// Text means: no NUL byte and valid UTF-8 within the first SNIFF_BYTES.
// `truncated` says the file continues past `prefix`, so a multi-byte
// character cut off at the end is not an error.
export function looksLikeText(prefix: Uint8Array, truncated: boolean): boolean {
  if (prefix.includes(0)) return false;
  try {
    new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(prefix, {
      stream: truncated,
    });
    return true;
  } catch {
    return false;
  }
}

export function attachment(filename: string): string {
  const encoded = encodeURIComponent(filename).replace(
    /['()*]/g,
    (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`,
  );
  return `attachment; filename*=UTF-8''${encoded}`;
}

export interface RawType {
  contentType: string;
  disposition: string | null;
}

// Content type for a file under raw/: images by extension, other text as
// text/plain, and everything else (markup and binary) as a download.
export function rawType(path: string, prefix: Uint8Array, truncated: boolean): RawType {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const ext = extension(name);
  const image = Object.hasOwn(IMAGE_TYPES, ext) ? IMAGE_TYPES[ext] : undefined;
  if (image) return { contentType: image, disposition: null };
  if (!MARKUP_EXTENSIONS.has(ext) && looksLikeText(prefix, truncated)) {
    return { contentType: TEXT, disposition: null };
  }
  return { contentType: OCTET, disposition: attachment(name) };
}

export function baseHeaders(contentType: string, csp: string, cacheControl: string): Headers {
  return new Headers({
    "Content-Type": contentType,
    "Content-Security-Policy": csp,
    "Cache-Control": cacheControl,
    "X-Content-Type-Options": "nosniff",
  });
}

// One `bytes=<first>-[<last>]` range, or null to ignore the header and send
// the whole object, which RFC 9110 allows. Git asks for a range when it
// resumes an interrupted pack download.
export function parseRange(
  header: string,
  size: number,
): { offset: number; length: number } | "unsatisfiable" | null {
  const match = /^bytes=(\d+)-(\d*)$/.exec(header);
  if (!match) return null;
  const first = Number(match[1]);
  if (!Number.isSafeInteger(first)) return null;
  if (match[2] && !Number.isSafeInteger(Number(match[2]))) return null;
  if (match[2] && Number(match[2]) < first) return null;
  if (first >= size) return "unsatisfiable";
  const last = Math.min(match[2] ? Number(match[2]) : size - 1, size - 1);
  return { offset: first, length: last - first + 1 };
}
