"""Users, passwords and sessions.

Identity is separate from role. A person signs in and receives a short-lived signed token that says only WHO they are.
Their role is read from the users table on every request, so an administrator changing a role, disabling an account or
resetting a password takes effect immediately, with no new token and no restart.

Passwords are hashed with scrypt and a random salt (never stored or logged). Sign-in answers the same way for an unknown
user and a wrong password, spends the same work either way, and locks an account for five minutes after five wrong
passwords (the counter lives in the database, so it holds across replicas).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

from .store import audit, utc

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1
MAX_FAILED, LOCK_SECONDS = 5, 300
SESSION_TTL_S = int(os.getenv("SESSION_TTL_S", "3600"))
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,39}$")
TOKEN_PREFIX = "sl1."
COMMON = {"password", "password1", "passw0rd", "123456789", "1234567890", "qwerty123", "letmein123", "admin12345", "welcome123"}


# ---------------------------------------------------------------- passwords
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(candidate, _unb64(digest))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("unused-placeholder-to-equalise-timing")


def password_problem(password: object, username: str = "") -> str | None:
    """Why a password is not acceptable, or None. Deliberately simple: length first, then the obvious traps."""
    if not isinstance(password, str):
        return "A password is required."
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    low = password.lower()
    if low in COMMON or (username and username.lower() in low) or len(set(password)) < 5:
        return "That password is too easy to guess. Use a longer phrase."
    return None


# ---------------------------------------------------------------- session tokens
def issue_token(secret: str, tenant: str, username: str, version: int, ttl: int = SESSION_TTL_S, now: float | None = None) -> tuple[str, int]:
    now = int(now if now is not None else time.time())
    payload = {"t": tenant, "u": username, "v": version, "iat": now, "exp": now + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{TOKEN_PREFIX}{body}.{sig}", payload["exp"]


def read_token(secret: str, token: str, now: float | None = None) -> dict | None:
    """The token's claims if the signature is genuine and it has not expired; otherwise None."""
    try:
        if not token.startswith(TOKEN_PREFIX) or len(token) > 600:
            return None
        body, sig = token[len(TOKEN_PREFIX):].split(".")
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        claims = json.loads(_unb64(body))
        if not isinstance(claims, dict) or claims.get("exp", 0) <= (now if now is not None else time.time()):
            return None
        return claims
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------- the users table
def public(row: dict, now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    return {"username": row["username"], "display_name": row["display_name"], "role": row["role"], "active": row["active"],
            "must_change_password": row["must_change_password"], "last_login": row["last_login"], "created_at": row["created_at"],
            "locked": bool(row["locked_until"] and row["locked_until"] > now)}


def get_user(db, username: str) -> dict | None:
    return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def list_users(db) -> list[dict]:
    return [public(r) for r in db.execute("SELECT * FROM users ORDER BY username").fetchall()]


def active_admins_except(db, username: str) -> int:
    return db.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=TRUE AND username<>?", (username,)).fetchone()["n"]


def create_user(db, actor: str, username: str, display_name: str, role: str, password: str, must_change: bool = True) -> dict:
    now = utc()
    db.execute("INSERT INTO users(username,display_name,role,password_hash,must_change_password,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
               (username, display_name, role, hash_password(password), must_change, now, now))
    audit(db, "user_created", username, {"actor": actor, "role": role})
    return public(get_user(db, username))


def update_user(db, actor: str, username: str, changes: dict) -> dict:
    before = get_user(db, username)
    sets, params, detail = [], [], {"actor": actor}
    if "role" in changes and changes["role"] != before["role"]:
        sets.append("role=?"); params.append(changes["role"]); detail.update({"role_from": before["role"], "role_to": changes["role"]})
    if "active" in changes and changes["active"] != before["active"]:
        sets.append("active=?"); params.append(changes["active"]); detail["active"] = changes["active"]
        if not changes["active"]:
            sets.append("token_version=token_version+1")  # a disabled account's sessions end now
    if "display_name" in changes and changes["display_name"] != before["display_name"]:
        sets.append("display_name=?"); params.append(changes["display_name"])
    if sets:
        db.execute(f"UPDATE users SET {', '.join(sets)}, updated_at=? WHERE username=?", (*params, utc(), username))
        action = "user_role_changed" if "role_to" in detail else "user_deactivated" if changes.get("active") is False else "user_reactivated" if "active" in detail else "user_updated"
        audit(db, action, username, detail)
    return public(get_user(db, username))


def set_password(db, actor: str, username: str, password: str, must_change: bool, action: str) -> None:
    db.execute("UPDATE users SET password_hash=?, must_change_password=?, token_version=token_version+1, failed_attempts=0, locked_until=NULL, updated_at=? WHERE username=?",
               (hash_password(password), must_change, utc(), username))
    audit(db, action, username, {"actor": actor})


def authenticate(db, username: str, password: str, now: float | None = None) -> tuple[dict | None, str]:
    """('user', 'ok') on success, else (None, 'invalid' | 'locked'). Always does the password work, and records the outcome."""
    now = now if now is not None else time.time()
    row = get_user(db, username)
    if row is None:
        verify_password(password, _DUMMY)
        return None, "invalid"
    if row["locked_until"] and row["locked_until"] > now:
        return None, "locked"
    ok = verify_password(password, row["password_hash"]) and row["active"]
    if not ok:
        failed = row["failed_attempts"] + 1
        if failed >= MAX_FAILED:
            db.execute("UPDATE users SET failed_attempts=0, locked_until=? WHERE username=?", (now + LOCK_SECONDS, username))
            audit(db, "login_locked", username, {"actor": username, "minutes": LOCK_SECONDS // 60})
        else:
            db.execute("UPDATE users SET failed_attempts=? WHERE username=?", (failed, username))
        audit(db, "login_failed", username, {"actor": username})
        return None, "invalid"
    db.execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_login=? WHERE username=?", (utc(now), username))
    audit(db, "login_success", username, {"actor": username})
    return get_user(db, username), "ok"


# ---------------------------------------------------------------- development seeding
DEV_USERS = {
    "t-acme": [("asha.admin", "Asha Rao", "admin"), ("omar.ops", "Omar Haddad", "operator"), ("vera.viewer", "Vera Lind", "viewer"), ("ari.audit", "Ari Cohen", "auditor")],
    "t-globex": [("gita.admin", "Gita Menon", "admin"), ("vik.viewer", "Vik Anand", "viewer")],
}


def seed_dev_users(path: str) -> None:
    """Create the development users and write their sign-ins to a git-ignored file. Existing users and passwords are kept."""
    import secrets
    from pathlib import Path

    from .store import Store

    store = Store(os.environ["DATABASE_URL"], os.getenv("REGION", "in"))
    file = Path(path)
    known = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {}
    for tenant, people in DEV_USERS.items():
        for username, display, role in people:
            key = f"{tenant}/{username}"
            with store.connect(tenant, lock=False) as db:
                if get_user(db, username):
                    continue
                password = known.get(key, {}).get("password") or secrets.token_urlsafe(12) + "-Aa1"
                create_user(db, "seed", username, display, role, password, must_change=False)
                known[key] = {"tenant": tenant, "username": username, "password": password, "role": role}
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(known, indent=2), encoding="utf-8")
    lines = ["Development sign-ins (local only, never commit this file)", ""] + [f"{v['tenant']:9} {v['role']:9} {v['username']:14} {v['password']}" for v in known.values()]
    file.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(known)} development users ready; sign-ins in {file.with_suffix('.txt')}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "seed":
        seed_dev_users(sys.argv[2] if len(sys.argv) > 2 else "data/dev-users.json")
    else:
        print("usage: python -m saas.users seed [path]")
