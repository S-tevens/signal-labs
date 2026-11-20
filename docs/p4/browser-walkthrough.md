# Dashboard browser walkthrough (final build)

- Date: 2026-11-21 (stack clock showed 2026-11-20 19:5x UTC)
- Commit: 22e90b6 (working tree had unrelated untracked files from others; no source edited)
- Method: Vite dev server at http://127.0.0.1:5173, built-in browser, live SaaS at https://127.0.0.1:8080, collector col-blr-01.
- Reaching the API: `dashboard/src/api.js` uses base `/api`, which `vite.config.js` proxies to `SAAS_PROXY_TARGET` (default `http://127.0.0.1:8000`). The default does not reach this stack. It was started with `SAAS_PROXY_TARGET=https://127.0.0.1:8080` and `NODE_EXTRA_CA_CERTS=data/certs/ca.pem` so Node trusts the private CA. The browser never talks TLS to the API, so it needs no certificate exception. The README or run script should say this.

| # | Check | Result | Detail |
|---|-------|--------|--------|
| a | Fleet shows collector with health state, resource usage, config hash | ISSUE | col-blr-01 shows a health state (Poor/Fair) and CPU, memory and latency columns. Config hash and host resources (cpu/disk/memory percent) are returned by `/v1/fleet` but are NOT shown anywhere in the fleet view. |
| b | Four health states and thresholds visible; stale/offline handling | PASS | Excellent/Good/Fair/Poor counters on the fleet page. Health history lists per-metric thresholds and "stale after 30s, offline after 40s", with stale and expired transitions in the log. Minor: the fleet table has no Stale/Offline label; the 5 silent collectors only show "Poor". |
| c | Tenant name and region shown | PASS | "Tenant: t-acme · Region: IN" banner; region tabs (India, Europe, All regions). |
| d | Incident explanation fields | PASS | Failed-logins incident 1903e907: signal, observed 30, method "local event summary", baseline and threshold "Not recorded" (stated explicitly), event time, alert time, payload link, recommendation, heuristic confidence. |
| e | Payload link opens stored observation, ID matches | PASS | `#/received?id=c95d4f12-...` showed the stored observation with the same payload_id, and a note that the stored fields are normalized. |
| f | Object explorer and health history open without errors | PASS | Both load and list data. Health history is a very long unpaginated list (hundreds of rows). |
| g | Data flow shows live counts | PASS | 6 collectors, 1 online, 92 incidents, 9013 proxy requests, 2/2 replicas healthy, 81574 retained payloads; "refreshes every 5 seconds". |
| h | Simulated action flow | PASS | Propose, Approve, Record rollback all worked end to end (audit lines action_proposed, action_approved, action_rolled_back). Labelled "Simulated actions ... No infrastructure commands are executed." The UI took about 3-8 s after each click to show the new state. |
| i | No console errors | ISSUE | One error: the Service name / Credential reference input `pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}"` (Platform.jsx lines 96-97) is not valid under the browser's `v` regex flag (unescaped `-` in a class), so the pattern is ignored. |
| j | Page updates by itself after new data | PASS | During a `cpu-spike` run the fleet page went from 694 to 695 alerts and col-blr-01 from 37 to 38 related alerts within about 9 s with no reload. Earlier, last-seen and alert counts also moved unprompted. |

## Issues for Member 2 to fix

1. Fleet view does not show config hash or host resource usage, although the API returns them (`config_hash`, `resources`). The CPU shown comes from the metric series (32%) while `resources.cpu_percent` is 0.6, so it is unclear which is "resource usage".
2. Console error: invalid `pattern` in Platform.jsx (lines 96-97); escape the hyphen (`[A-Za-z0-9_.\-]`) or move it to the end. Validation does not work until this is fixed.
3. Offline collectors show only "Poor" and raw seconds ("17787s ago"); show a Stale/Offline label and a readable age (for example "4 h ago").
4. The "Dashboard latency p95" tile showed `252.5 s` against a target of 10 s (and a dash earlier). Check the unit or calculation, or explain it.
5. Health history entries such as "cpu ... reported Poor; value 69.8 %" sit under a Poor threshold of >= 95. The reason text does not explain why it is Poor. The page is also unpaginated.
6. Many old test collectors (col-measure-off-*, col-enrolled-*) remain in the tenant and keep the fleet at Poor. This is data hygiene, not a code fault.
7. First load took a few seconds ("Loading live data", counters at 0) because the proxy responses took 2-3 s each. Consider a loading state that is clearer.

## Not checked

- A real Europe/EU region view (only the IN account token was used; "All regions" is demo data).
- Browser trust of the private CA directly (the dev proxy bypasses it).
- Production build (`dist`) or mobile layout; only the Vite dev server at desktop size.
- Analytics, Performance proof and Local egress pages were not opened.
- Baseline and threshold on a metric-based incident (the failed-logins incident has none recorded).

## Fixes applied (2026-11-21)

Checked again in the browser after the change; production build passes.

| Issue | Fix | Result |
|---|---|---|
| 1. Fleet view hid the config hash and resources | The collector cell now shows the process CPU, memory and disk share and the config hash under its name (`dashboard/src/App.jsx`, `api.js`) | Shown: `cpu 0.17% · mem 0.67% · disk 67.5% · config cfg-d799...`; older collectors that never sent a report show "no resource report" and `config dev` |
| 2. Invalid `pattern` regex console error | Hyphen escaped in both inputs (`Platform.jsx`) | The pattern is valid under the browser's `v` flag |
| 3. Offline shown as "Poor" with raw seconds | Presence label (Live, Stale after 30 s, Offline) and readable ages ("5 h ago") | Shown: `Live · 3 s ago`, `Offline · 5 h ago`, `Offline · 34 min ago` |
| 4. Latency p95 tile at 252 s; dev proxy missed the stack | The tile counted payloads that were already stored when the page opened as live renders, so their age became "latency". The first snapshot is no longer acknowledged and only payloads under 30 s old are. The dev proxy now reads `data/run.env.json` (address and private CA, certificate still verified) when `SAAS_PROXY_TARGET` is not set | After a reload, 0 acknowledgements in the first 7 s and 26 live ones in the next 30 s; `/api/healthz` reaches the TLS stack with no overrides |

The tile's 5-minute window still holds earlier acknowledgements for up to five minutes, so it takes that long to show only fresh samples. Samples already stored in the database are not rewritten. Issues 5 to 7 above (health-history wording and pagination, old test collectors, loading state) are not changed.
