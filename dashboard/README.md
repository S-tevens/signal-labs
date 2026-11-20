# Signal Labs dashboard

React + Vite dashboard for the platform owner. Run `npm ci && npm run dev` in `dashboard/`; open http://127.0.0.1:5173. `npm run build` validates the production bundle.

With no `VITE_DASHBOARD_TOKEN`, the screens use synthetic fixtures. Configure a local dashboard bearer token and API URL through `.env.local` (see `.env.example`) for live SaaS data. The dev proxy forwards `/api` to `SAAS_PROXY_TARGET`; `VITE_SAAS_URL` can point to a different endpoint if CORS is configured. Vite embeds `VITE_*` values into the browser bundle. This is suitable only for a controlled local demo; production requires a login and short-lived credentials. Never put collector secrets in browser configuration.

The dashboard provides Fleet, Incidents, Performance Proof, Object Explorer, Health History and a synthetic Local Egress view. Live incident details link collectors, sources, payload evidence and recommendations, and let authorized operators propose/approve/reject/roll back simulated actions. The backend enforces roles; actions never execute commands. The dashboard listens to authenticated SSE snapshots and falls back to bounded polling if disconnected. Live errors show stale status rather than substituting fixtures.

The Local Egress sample is synthetic. Never proxy real raw data through centrally hosted SaaS. Member 1 must deploy its real raw/egress view inside the customer environment with local authorization. Performance proof uses a recent five-minute window; client acknowledgements and clock skew affect latency. Compare the received ID set with collector-local sent IDs before claiming no loss.
