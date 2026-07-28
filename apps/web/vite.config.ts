import { defineConfig } from "vite";
import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// pneuma-knowledge experiment bench UI. base "./" so build output can be served from any
// path. In dev, the browser calls the API same-origin (VITE_API_BASE empty) and
// vite proxies /v1 + /healthz to the local service (scripts/dev-api.sh).
const API_TARGET = process.env.PNEUMA_KNOWLEDGE_API_PORT
  ? `http://127.0.0.1:${process.env.PNEUMA_KNOWLEDGE_API_PORT}`
  : "http://127.0.0.1:18000";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // ws: true is load-bearing, not decoration — /v1/users/{uid}/live-context/ws is a
      // WebSocket upgrade, and without it the dev proxy answers the handshake with a plain
      // HTTP response and the socket never opens (the ContextStream view's WS transport dies).
      "/v1": { target: API_TARGET, changeOrigin: true, ws: true },
      "/healthz": { target: API_TARGET, changeOrigin: true },
    },
  },
  resolve: {
    alias: [
      {
        find: /^@\//,
        replacement: `${fileURLToPath(new URL("./src", import.meta.url))}/`,
      },
    ],
  },
});
