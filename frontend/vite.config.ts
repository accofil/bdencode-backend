import { readFileSync } from "node:fs";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const { version } = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as { version: string };

export default defineConfig({
  base: "/encoder/",
  plugins: [react()],
  // The interface's own version, to tell a stale browser tab from the server.
  define: { __APP_VERSION__: JSON.stringify(version) },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    assetsDir: "assets",
  },
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/encoder/api": {
        target: "http://127.0.0.1:8796",
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/encoder/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
