# Signal Labs SaaS

The platform uses FastAPI and PostgreSQL. Run from the repository root using Python 3.11+ and a local PostgreSQL instance. The root README contains the native local quick start. Install `saas/requirements.txt`, set `ADMIN_DATABASE_URL` and `SAAS_DB_PASSWORD`, and run `python -m saas.migrate`; configure the restricted `DATABASE_URL`, `REGION` and `SAAS_AUTH_JSON`, then run `uvicorn saas.main:app --host 127.0.0.1 --port 8000`.

The application role cannot be a superuser or bypass RLS. The first regional replica binds its database to `REGION`; each region needs a separate database. Same-region replicas may share it. An individual Postgres instance is a single point of failure. Local HTTP is for development; when certificates are available, Uvicorn supports `--ssl-certfile <cert> --ssl-keyfile <key>` and the collector must verify the CA. See `docs/p2/architecture.md`.

Run `python -m pytest -q collector saas`. Database tests skip unless `TEST_DATABASE_URL` points to a **dedicated, migrated, disposable** test database; tests delete synthetic tenants there. Set `TEST_DATABASE_URL_EU` to a second dedicated migrated database to run the regional test. CI creates and tests two disposable databases.

See `contracts/api.md` for object, lineage, action, proof, and enrollment endpoints. Action execution is deliberately simulated. Enrollment tokens and collector keys are hashed, but verification currently requires the signing secret in the tenant-scoped database. TLS, managed encrypted secrets, credential revocation/rotation, rate limiting, and individual user identities remain production work. Raw logs and the real egress view must stay local to the customer.
