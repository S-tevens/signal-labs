import { defineConfig } from "vite";

// In dev, /api/* is forwarded to the SaaS so the browser sees one origin (no CORS setup needed).
// Point it at another replica or a load balancer with SAAS_PROXY_TARGET.
export default defineConfig({
  server: {
    proxy: {
      "/api": {
        target: process.env.SAAS_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
