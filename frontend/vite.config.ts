import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開発時はViteが5173で動き、APIとWSはバックエンド(8000)へ中継する。
// 本番はFastAPIが dist/ を配信するので、この中継は開発専用
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["tests/setup.ts"],
    globals: true,
  },
});
