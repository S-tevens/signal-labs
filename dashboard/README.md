# Signal Labs dashboard

React + Vite frontend for Member C. All changes are contained in `dashboard/`.

```sh
cd dashboard
npm install
npm run dev
```

Open http://127.0.0.1:5173. Run `npm run build` for the production bundle.

## Implemented views

- `#/fleet`: region selection, health filtering, collector search, CPU/latency charts, collector details, stale-data handling.
- `#/incidents`: severity filtering, grouped alerts, contributing signals and explained recommendations.
- `#/proof`: illustrative performance targets, delivery counts and downloadable demo evidence.
- `#/egress`: **synthetic local-only demo**, raw vs. approved metadata, field treatment and payload download/copy.

All numbers are fixtures in `src/data.js`, visibly labeled Demo data. Refresh re-reads the same snapshot; it does not fetch a backend. Charts follow the selected demo region. A cross-region option is a demo convenience, not proof of deployed regional residency. No remediation executes, and confidence labels are illustrative heuristics.

## Backend handoff

Member A/B must finalize response shapes in `contracts/api.md`. No contract files were changed here. Match fixtures to the agreed shapes and replace their imports with authenticated fetches:

| View           | Planned endpoint                          |
| -------------- | ----------------------------------------- |
| Fleet          | `GET /v1/fleet`                           |
| Charts         | `GET /v1/metrics?source=&name=&from=&to=` |
| Incidents      | `GET /v1/incidents`                       |
| Health history | `GET /v1/health/history`                  |
| Proof          | `GET /v1/proof`                           |
| Live updates   | `GET /v1/stream`                          |

Implement loading, explicit errors and stale-data states when adding network access. Do not silently fall back to demo values after a live request fails. Credentials and tenant authorization must be enforced by the backend, not a UI selector. Collector secrets must never enter the frontend bundle.

**Local egress boundary:** the current raw sample is fabricated. Do not connect `/local/raw` or `/local/egress` to a centrally hosted SaaS dashboard or proxy raw records through SaaS. Deploy the local view separately inside the customer environment and use collector-local authorization. Only then replace the synthetic sample with local API calls. The local view must not send raw records to remote analytics, logging, or other services. No raw records are persisted by this prototype.

Production evidence requires measured event/render times, documented sampling windows, clock handling, and matching sent/received unique payload ID sets. Fixture counts are not reliability proof.

Google Fonts is optional: the CSS includes local system-font fallbacks. For the final customer-local deployment, self-host fonts and remove the external import.
