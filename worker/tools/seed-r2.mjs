// Load actual publisher output into Miniflare's local-only Wrangler store.
// This program never reads credentials and never creates a remote binding.
import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { Miniflare } from "miniflare";

const [directory, persistence] = process.argv.slice(2);
if (!directory || !persistence) throw new Error("usage: seed-r2.mjs OUTPUT PERSISTENCE");
const mf = new Miniflare({
  // Wrangler's pinned Miniflare 5 stores resources below <persist>/v3.
  // Use its current config/manifest API instead of the old script/r2Persist
  // options, which are no longer accepted by new Miniflare().
  resourcePersistencePath: join(persistence, "v3"),
  cf: false,
  telemetry: { enabled: false },
  workers: [
    {
      config: {
        name: "synthetic-seed",
        compatibilityDate: "2026-10-01",
        manifest: {
          mainModule: "seed.js",
          modules: {
            "seed.js": {
              type: "esm",
              contents: "export default {fetch() {return new Response('local seed')}}",
            },
          },
        },
        env: { BUCKET: { type: "r2", name: "replace-me", dev: { remote: false } } },
      },
    },
  ],
});
async function files(directory, prefix = "") {
  const paths = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const key = prefix ? `${prefix}/${entry.name}` : entry.name;
    if (entry.isDirectory()) paths.push(...(await files(join(directory, entry.name), key)));
    else if (entry.isFile()) paths.push(key);
    else throw new Error(`unexpected publisher output type: ${key}`);
  }
  return paths;
}
try {
  const bucket = await mf.getR2Bucket("BUCKET");
  // Mirror, including deletions: stale local objects must not mask a mismatch
  // between the publisher's grace sweep and the Worker's lookups.
  let cursor;
  do {
    const page = await bucket.list({ cursor });
    for (const object of page.objects) await bucket.delete(object.key);
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  const keys = await files(directory);
  for (const key of keys) await bucket.put(key, await readFile(join(directory, key)));
  console.log(`seed-r2: ${keys.length} synthetic objects loaded locally`);
} finally {
  await mf.dispose();
}
