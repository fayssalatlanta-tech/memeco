/**
 * Vite config for the Memeco SPA bundle.
 *
 * Multi-page setup: each browser route ("/system", "/", "/whale-radar",
 * "/wallet", "/token") gets its own HTML entry that boots the right
 * page module. We keep the entry HTML files dumb (just an empty mount
 * point + the entry script tag); all rendering lives in the JS.
 *
 * Output:
 *   web/dist/
 *     system/index.html
 *     dashboard/index.html        (when added)
 *     ...
 *     assets/<hashed bundles>
 *
 * FastAPI serves the dist folder via /static/dist/* and prefers the
 * built version of any page when present, falling back to the legacy
 * app/static/<page>.html otherwise. So you can migrate pages one at a
 * time without breaking anything.
 */
import { defineConfig } from "vite";
import { resolve } from "node:path";

export default defineConfig({
  root: resolve(__dirname, "src"),
  base: "/static/dist/",
  publicDir: false,
  build: {
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      input: {
        // One entry per migrated page. Add new keys as more pages move
        // to the Vite build.
        system: resolve(__dirname, "src/pages/system/index.html"),
        wallet: resolve(__dirname, "src/pages/wallet/index.html"),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Devs running `npm run dev` proxy API calls to the running
      // FastAPI server on :8000 so the page actually has data.
      "/api": "http://127.0.0.1:8000",
    },
  },
});
