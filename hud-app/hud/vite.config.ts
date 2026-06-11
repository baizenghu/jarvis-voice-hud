import { defineConfig } from "vite";

// base: "./" → relative asset paths so the built app works when served from the
// dist root by dev_server.py. outDir: "dist" is where StaticFiles mounts it.
export default defineConfig({
  base: "./",
  build: {
    outDir: "dist",
  },
});
