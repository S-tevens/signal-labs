import { defineConfig } from "vite";
import fs from "node:fs";
import https from "node:https";
import path from "node:path";

// In dev, /api/* is forwarded to the SaaS so the browser sees one origin (no CORS setup needed).
// Target, in order: SAAS_PROXY_TARGET, the address that scripts/run-local.ps1 recorded in data/run.env.json
// (with its private CA, so the certificate is still verified), then http://127.0.0.1:8000.
function recorded() {
  try {
    return JSON.parse(fs.readFileSync(path.resolve(__dirname, "../data/run.env.json"), "utf8"));
  } catch {
    return {};
  }
}
const run = recorded();
const target = process.env.SAAS_PROXY_TARGET || run.saas_url || "http://127.0.0.1:8000";
const agent = target.startsWith("https") && run.ca && fs.existsSync(run.ca) ? new https.Agent({ ca: fs.readFileSync(run.ca) }) : undefined;

// On the public address (PUBLIC_MODE=1) the browser may only use what the dashboard needs. Collector traffic (ingest,
// heartbeat, enrollment) is refused here, whatever credentials are presented.
const BLOCKED_PUBLIC = /^\/api\/v1\/(ingest|heartbeat|enroll|enrollment-tokens)(\/|\?|$)/;
const proxy = {
  "/api": {
    target,
    changeOrigin: true,
    agent,
    rewrite: (p) => p.replace(/^\/api/, ""),
    bypass(req, res) {
      if (process.env.PUBLIC_MODE === "1" && BLOCKED_PUBLIC.test(req.url || "")) {
        res.statusCode = 403;
        res.end("not available on the public address");
        return false;
      }
      return undefined;
    },
  },
};

export default defineConfig({
  server: { proxy },
  // `vite preview` serves the built dashboard; a tunnel presents its own host name, so any Host header is allowed there.
  preview: { proxy, allowedHosts: true },
});
