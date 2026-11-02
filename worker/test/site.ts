// Seed the bucket with a published site laid out the way the publisher
// writes it (src/partlet/publish.py, gitstatic.py, site/render.py).
import { env } from "cloudflare:workers";

export const SOURCE = "test";
export const BUILD = "7e8b3f9bae3d6b4f";
export const TIP = "0388eccc54e23fceeb8d075004aed6ff082a92db";
export const PACK = "pack-3e4b03e8469867eeca8958e4bf4a8ca2d484f1a5";

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0]);

export const BLOBS: Record<string, string | Uint8Array> = {
  "README.md": "# Foo\n",
  "docs/a.md": "x\n",
  "docs/index.html/leaf.txt": "leaf\n",
  "a!'()*~.txt": "marks\n",
  "sp ace/f #1?.txt": "h#?%\n",
  "ünï.txt": "hi\n",
  "evil.html": "<script>alert(1)</script>",
  "evil.svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
  "evil.js": "alert(1)\n",
  "img/logo.png": PNG,
  "bin/data": new Uint8Array([1, 2, 0, 3]),
  empty: "",
  "latin1.txt": new Uint8Array([0x63, 0x61, 0x66, 0xe9]),
};

export async function put(key: string, value: string | Uint8Array): Promise<void> {
  await env.BUCKET.put(`${SOURCE}/${key}`, value);
}

export async function seedProject(name = "foo", build = BUILD, tip = TIP): Promise<void> {
  const p = `p/${name}`;
  await put(
    `${p}/current`,
    JSON.stringify({
      build,
      tip,
      name,
      description: "Foo tool",
      updated: "2026-10-17T12:00:00+00:00",
      // Written by the publisher for its sweep; the Worker ignores it.
      previous: { build: null, tip: null, packs: [] },
    }),
  );
  await put(`${p}/git/HEAD`, "ref: refs/heads/main\n");
  await put(`${p}/git/info/refs`, `${tip}\trefs/heads/main\n`);
  await put(`${p}/git/objects/info/packs`, `P ${PACK}.pack\n\n`);
  await put(`${p}/git/objects/pack/${PACK}.pack`, "PACK-bytes-0123456789");
  await put(`${p}/git/objects/pack/${PACK}.idx`, "IDX-bytes");
  await put(`${p}/site/${build}/index.html`, `<p>project ${name}</p>`);
  await put(`${p}/site/${build}/tree/docs/index.html`, "<p>tree docs</p>");
  await put(
    `${p}/site/${build}/tree/docs/children/index.html/index.html`,
    "<p>tree docs/index.html</p>",
  );
  await put(`${p}/site/${build}/tree/sp ace/index.html`, "<p>tree sp ace</p>");
  for (const [path, data] of Object.entries(BLOBS)) {
    await put(`${p}/site/${build}/blob/${path}`, `<p>blob ${path}</p>`);
    await put(`${p}/site/${build}/raw/${path}`, data);
  }
  await put(`${p}/archive/${tip}.tar.gz`, "TGZ");
  await put(`${p}/archive/${tip}.zip`, "ZIP");
}

export async function seedSite(): Promise<void> {
  await put("index.html", "<p>site index</p>");
  await put("index.json", "[]\n");
  await put("static/style.css", "body{}\n");
  await seedProject();
}
