"""Collector enrollment: trade a one-time token for this collector's own credentials.

    # on the platform, an admin creates a token for this collector (POST /v1/enrollment-tokens), then, on this machine:
    set ENROLL_TOKEN=<token>        # or --token-file; --token works but is visible in the process list
    python -m collector.enroll --saas-url https://saas.example --ca ca.pem --tenant t-acme

    # or let the collector do it on first start:
    ENROLL_TOKEN=... ENROLL_TENANT=t-acme python -m uvicorn collector.main:app

What happens: the collector POSTs {tenant_ref, token} to /v1/enroll over VERIFIED TLS and receives its collector id,
key and signing secret exactly once. It also creates its own pseudonym secret locally (that one never leaves).
Everything is saved to <DATA_DIR>/credentials.json, readable only by its owner. From then on the collector uses these
instead of the built-in dev defaults. The token is spent: it cannot be used again.

Safety rules enforced here
  * The token and the returned secrets only ever travel over HTTPS. Plain HTTP is refused unless you explicitly
    pass --insecure-http-for-dev (a trusted loopback demo only).
  * The server certificate is always verified; only the configured CA is trusted.
  * Neither the token nor any secret is printed, logged or placed in an error message.
  * If saving fails after the platform has issued credentials, the token is already spent: ask for a new one.
  * Enrolling again needs --force (it replaces the credentials, and keeps the existing pseudonym secret so source
    ids stay stable).

Not built: rotating or revoking a collector's credentials from the collector side.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import credentials
from .sender import tls_context

TENANT = re.compile(r"^t-[a-z0-9-]{1,40}$")
COLLECTOR = re.compile(r"^col-[a-z0-9-]{1,40}$")


class EnrollmentError(RuntimeError):
    """Enrollment failed. The message never contains the token or any secret."""


def enroll(saas_url: str, tenant_ref: str, token: str, ca_file: str = "", timeout: float = 10.0, allow_http: bool = False) -> dict:
    """Exchange the token for credentials. Returns the credentials (not yet saved)."""
    url = saas_url.rstrip("/")
    https = url.lower().startswith("https://")
    if not https and not allow_http:
        raise EnrollmentError(
            "refusing to send an enrollment token over plain HTTP; use an https:// SaaS URL "
            "(or --insecure-http-for-dev on a trusted loopback demo)"
        )
    if not TENANT.fullmatch(tenant_ref or ""):
        raise EnrollmentError("the tenant reference must look like t-acme")
    if not token or not 20 <= len(token) <= 128:
        raise EnrollmentError("no valid enrollment token was provided")
    try:
        with httpx.Client(verify=tls_context(ca_file) if https else True, timeout=timeout) as client:
            resp = client.post(f"{url}/v1/enroll", json={"tenant_ref": tenant_ref, "token": token})
    except httpx.HTTPError as exc:
        raise EnrollmentError(f"could not reach {url}: {type(exc).__name__}") from None  # no body, no token
    if resp.status_code == 401:
        raise EnrollmentError("the enrollment token is invalid, expired or already used")
    if resp.status_code == 422:
        raise EnrollmentError("the platform rejected the request; check the tenant reference")
    if resp.status_code != 200:
        raise EnrollmentError(f"enrollment failed with HTTP {resp.status_code}")
    try:
        data = resp.json()
        got = {k: data[k] for k in ("collector_id", "tenant_ref", "region", "collector_key", "collector_secret")}
    except (ValueError, KeyError, TypeError):
        raise EnrollmentError("the platform's reply was not a valid enrollment response") from None
    if not all(isinstance(v, str) and v for v in got.values()):
        raise EnrollmentError("the platform's reply was not a valid enrollment response")
    if got["tenant_ref"] != tenant_ref or not COLLECTOR.fullmatch(got["collector_id"]):
        raise EnrollmentError("the platform's reply does not match the request")
    return {**got, "saas_url": url, "enrolled_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def enroll_and_save(data_dir, saas_url, tenant_ref, token, ca_file="", force=False, allow_http=False) -> tuple[Path, bool, dict]:
    """Enroll and store the credentials. Returns (path, permissions_restricted, creds_without_secrets)."""
    previous = credentials.load(data_dir)
    if previous and not force:
        raise EnrollmentError(f"already enrolled as {previous['collector_id']}; use --force to enroll again")
    creds = enroll(saas_url, tenant_ref, token, ca_file=ca_file, allow_http=allow_http)
    # The pseudonym secret is created here and never leaves. Keep the old one on re-enrollment so source ids stay stable.
    creds["pseudo_secret"] = previous["pseudo_secret"] if previous else secrets.token_hex(32)
    path, restricted = credentials.save(data_dir, creds)
    return path, restricted, {k: v for k, v in creds.items() if k not in ("collector_key", "collector_secret", "pseudo_secret")}


def ensure_enrolled(cfg):
    """First-start enrollment: if ENROLL_TOKEN is set and this collector has no credentials yet, enroll now.

    Returns a Config that uses the new credentials. With no token set, or already enrolled, returns `cfg` unchanged.
    """
    token = os.getenv("ENROLL_TOKEN", "")
    if not token or str(cfg.data_dir) == ":memory:" or credentials.exists(cfg.data_dir):
        return cfg
    tenant = os.getenv("ENROLL_TENANT", "")
    if not tenant:
        raise EnrollmentError("ENROLL_TOKEN is set but ENROLL_TENANT (for example t-acme) is not")
    enroll_and_save(cfg.data_dir, cfg.saas_url, tenant, token, ca_file=cfg.saas_ca_file, allow_http=os.getenv("ENROLL_ALLOW_HTTP") == "1")
    from .config import Config

    return Config()  # read the credentials just saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saas-url", default=os.getenv("SAAS_URL", ""), help="platform base URL (https)")
    ap.add_argument("--tenant", default=os.getenv("ENROLL_TENANT", ""), help="tenant reference, for example t-acme")
    ap.add_argument("--token-file", help="file containing the enrollment token (preferred)")
    ap.add_argument("--token", help="the token itself (visible in the process list; prefer ENROLL_TOKEN or --token-file)")
    ap.add_argument("--ca", default=os.getenv("SAAS_CA_FILE", ""), help="CA file that signed the platform's certificate")
    ap.add_argument("--data-dir", default=os.getenv("DATA_DIR", "./data/collector"))
    ap.add_argument("--force", action="store_true", help="replace existing credentials")
    ap.add_argument("--insecure-http-for-dev", action="store_true", help="allow plain HTTP (trusted loopback demo only)")
    args = ap.parse_args(argv)

    token = args.token or os.getenv("ENROLL_TOKEN", "")
    if args.token_file:
        try:
            token = Path(args.token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            print(f"cannot read the token file: {type(exc).__name__}", file=sys.stderr)
            return 2
    try:
        path, restricted, info = enroll_and_save(
            args.data_dir, args.saas_url, args.tenant, token, ca_file=args.ca, force=args.force, allow_http=args.insecure_http_for_dev
        )
    except (EnrollmentError, credentials.CredentialsError) as exc:
        print(f"enrollment failed: {exc}", file=sys.stderr)
        return 1
    print(f"Enrolled {info['collector_id']} for tenant {info['tenant_ref']} (region {info['region']}).")
    print(f"Credentials saved to {path}" + ("" if restricted else "  WARNING: could not restrict the file to its owner; do it yourself."))
    print("The token is now spent. Start the collector as usual: it will use these credentials.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
