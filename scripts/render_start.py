"""Start command on Render: prepare the database, create the sign-ins, then serve the platform and the dashboard.

Reads ADMIN_DATABASE_URL (Render's database), SAAS_DB_PASSWORD, COLLECTOR_KEY, COLLECTOR_SECRET, SEED_PASSWORD and PORT.
The application connects as a restricted role (no superuser, no BYPASSRLS) when the database lets us create one; otherwise it
uses the database owner, which row-level security still applies to (the tables use FORCE ROW LEVEL SECURITY).
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import psycopg  # noqa: E402

admin = os.environ["ADMIN_DATABASE_URL"].replace("postgres://", "postgresql://", 1)
os.environ["ADMIN_DATABASE_URL"] = admin
role = os.getenv("SAAS_DB_USER", "signal_app")
parts = urlsplit(admin)
netloc = f"{role}:{quote(os.environ['SAAS_DB_PASSWORD'], safe='')}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
app_url = urlunsplit(parts._replace(netloc=netloc))

with psycopg.connect(admin) as db:
    ready = db.execute("SELECT to_regclass('signal.payloads')").fetchone()[0] is not None
if not ready:
    from saas import migrate

    try:
        migrate.main()
    except Exception as exc:  # the host may not allow creating a role: apply the schema as the owner instead
        print(f"Restricted role not available ({exc.__class__.__name__}); using the database owner", flush=True)
        with psycopg.connect(admin) as db:
            for f in sorted((ROOT / "saas" / "migrations").glob("*.sql")):
                db.execute(f.read_text(), prepare=False)
try:
    psycopg.connect(app_url, connect_timeout=8).close()
    os.environ["DATABASE_URL"] = app_url
except Exception:
    os.environ["DATABASE_URL"] = admin

region = os.getenv("REGION", "in")
os.environ["REGION"] = region
os.environ["SAAS_AUTH_JSON"] = json.dumps({
    "collectors": {os.environ["COLLECTOR_KEY"]: {"tenant": "t-acme", "region": region, "collector": "col-blr-01", "secret": os.environ["COLLECTOR_SECRET"]}},
    "dashboard": {},
})
os.environ["SAAS_DISABLE_API_TOKENS"] = "1"

from saas.users import seed_dev_users  # noqa: E402

seed_dev_users("data/dev-users.json")

os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "saas.web:app", "--host", "0.0.0.0", "--port", os.getenv("PORT", "10000"),
                          "--proxy-headers", "--forwarded-allow-ips", "*"])
