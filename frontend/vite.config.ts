/// <reference types="vitest" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the browser talks only to Vite (:5173); /api is proxied to FastAPI (:8000),
// so cookies are same-origin and no CORS is needed. In production FastAPI serves dist/ itself.
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: { manualChunks: { vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"], charts: ["recharts"] } },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
