import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/image-studio/",
  plugins: [react()],
  server: {
    port: 18141,
    proxy: {
      "/image-studio/api": {
        target: "http://127.0.0.1:18140",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/image-studio/, ""),
      },
      "/image-studio/health": {
        target: "http://127.0.0.1:18140",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/image-studio/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
