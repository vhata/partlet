import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.toml" },
      // Tests use their own source prefix, never the deploy placeholder.
      miniflare: { bindings: { SOURCE: "test" }, cf: false },
    }),
  ],
});
