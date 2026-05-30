import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimal typing for the Node globals used below (avoids a full @types/node dep).
declare const process: { env: Record<string, string | undefined> };

// Dev server proxies /api to the FastAPI read API (uvicorn on :8000 by default;
// override with VITE_API_TARGET, e.g. for tests or a remote backend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.VITE_PORT) || 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
