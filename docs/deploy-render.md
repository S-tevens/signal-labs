# Deploy on Render

One web service (platform API + built dashboard, `saas/web.py`) and one Postgres database, described in `render.yaml`.
The collector and simulator stay on the customer's machine and push metadata to the service.

1. Push the branch you deploy to GitHub (Render builds from the repository).
2. Render dashboard: **New > Blueprint**, pick the repository and branch. It reads `render.yaml`.
3. When asked, fill in:
   - `SEED_PASSWORD`: the password for all demo accounts (12+ characters).
   - `GEMINI_API_KEY`: the AI engine's key.
4. Wait for the build (about 5 minutes). The address is `https://signal-labs.onrender.com` (or the name Render shows).
5. Service > **Environment**: copy `COLLECTOR_KEY` and `COLLECTOR_SECRET`.
6. On the laptop:
   `.\scripts\push-to-cloud.ps1 -Url https://signal-labs.onrender.com -Key <COLLECTOR_KEY> -Secret <COLLECTOR_SECRET>`
7. Sign in with organization `t-acme` and a username from `saas/users.py` (`asha.admin`, `omar.ops`, `vera.viewer`, `ari.audit`) and `SEED_PASSWORD`.
   Give the simulator about two minutes for its baseline.

Notes
- The free web service sleeps after about 15 idle minutes and takes up to a minute to wake: open it before the evaluation. The free database expires after 30 days.
- Startup (`scripts/render_start.py`) creates the schema, uses a restricted database role when Render allows one (otherwise the owner; row-level security still applies), seeds the users and starts the server.
- The browser reaches `/api/v1/...`; collector routes (enrollment, tokens) are refused there. Collectors use `/v1/ingest` and `/v1/heartbeat`, which need the key and HMAC signature.
- Static API tokens are off. Stop the local simulator with `.\scripts\push-to-cloud.ps1 -Stop`.
