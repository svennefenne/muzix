import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: `npm run dev` proxies the API to a Muzix backend on :18080
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:18080", changeOrigin: false } },
  },
  // source maps let crash reports from browsers (POST /api/client-errors) be read back to the source
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 1500 },
});
