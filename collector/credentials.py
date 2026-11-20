"""The collector's own credentials, issued by the platform at enrollment and stored locally.

The file holds the collector key, its signing secret and the local pseudonym secret. It is written atomically and
restricted to its owner BEFORE any secret is put in it, so there is no window where it is readable by others.
Nothing in this module logs or returns secret values in error messages.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

CREDENTIALS_FILE = "credentials.json"
REQUIRED = ("collector_id", "tenant_ref", "region", "collector_key", "collector_secret", "pseudo_secret", "saas_url")


class CredentialsError(RuntimeError):
    """The credentials file exists but cannot be used. The collector refuses to guess."""


def path_for(data_dir: str | Path) -> Path:
    return Path(data_dir) / CREDENTIALS_FILE


def exists(data_dir: str | Path) -> bool:
    return str(data_dir) != ":memory:" and path_for(data_dir).is_file()


def load(data_dir: str | Path) -> dict | None:
    """Return the stored credentials, None if this collector has not enrolled, or raise if the file is damaged."""
    if not exists(data_dir):
        return None
    try:
        data = json.loads(path_for(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CredentialsError(f"credentials file {path_for(data_dir)} cannot be read: {type(exc).__name__}") from None
    missing = [k for k in REQUIRED if not isinstance(data, dict) or not isinstance(data.get(k), str) or not data.get(k)]
    if missing:
        raise CredentialsError(f"credentials file {path_for(data_dir)} is missing or has empty fields: {', '.join(missing)}")
    return data


def restrict_permissions(path: Path) -> bool:
    """Make the file readable by its owner only. Returns False if that could not be confirmed (best effort)."""
    try:
        if os.name == "nt":
            user = os.environ.get("USERNAME", "")
            if not user:
                return False
            # Remove inherited permissions, then grant only the current user.
            done = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True, timeout=15)
            return done.returncode == 0
        os.chmod(path, 0o600)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def save(data_dir: str | Path, creds: dict) -> tuple[Path, bool]:
    """Write the credentials atomically. Returns (path, permissions_restricted)."""
    missing = [k for k in REQUIRED if not creds.get(k)]
    if missing:
        raise CredentialsError(f"refusing to save incomplete credentials, missing: {', '.join(missing)}")
    target = path_for(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(b"")  # create it empty first
    restricted = restrict_permissions(tmp)  # ...lock it down...
    try:
        with open(tmp, "wb") as fh:  # ...and only then put secrets in it
            fh.write(json.dumps(creds, indent=2, sort_keys=True).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)  # atomic: a crash leaves either the old file or the new one, never half of one
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return target, restricted
