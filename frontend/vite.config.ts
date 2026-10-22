import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// dev: `npm run dev` proxies the API to a Muzix backend on :18080
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:18080", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1500 },
});
