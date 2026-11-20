"""Role-based access control: one permission matrix that every dashboard route goes through.

Roles (least privilege first):
  viewer    reads everything in its own tenant: fleet, metrics, incidents, lineage, proof, history.
  auditor   viewer, plus: reads the audit log. Cannot act on incidents or manage anything (for compliance and security review).
  operator  viewer, plus: asks for an AI summary, proposes simulated actions, approves and rolls them back.
  admin     operator, plus: issues one-time collector enrollment tokens, reads the audit log and manages users and roles.

Rules that matter:
  * Unknown roles and unknown permissions get nothing (fail closed). A misspelt role in the configuration stops the
    service at start instead of quietly granting or denying the wrong thing.
  * A role never crosses a tenant: the tenant comes from the authenticated token, never from the request.
  * Collectors are a separate kind of principal (signed requests to ingest and heartbeat only); they hold no dashboard role.
  * Every refused request is written to the audit log (who, role, permission, path), never the credential.
"""
from __future__ import annotations

ROLES = ("viewer", "auditor", "operator", "admin")

_VIEWER = frozenset({"read"})
_AUDITOR = _VIEWER | {"audit.read"}
_OPERATOR = _VIEWER | {"ai.summary", "action.propose", "action.decide"}
_ADMIN = _OPERATOR | {"enrollment.create", "audit.read", "users.manage"}

GRANTS: dict[str, frozenset[str]] = {"viewer": _VIEWER, "auditor": _AUDITOR, "operator": _OPERATOR, "admin": _ADMIN}

PERMISSIONS = {
    "read": "See the fleet, metrics, incidents, evidence, lineage and proof for the tenant",
    "ai.summary": "Ask for an AI-written incident summary (sends incident metadata to the AI provider)",
    "action.propose": "Propose a simulated remediation action",
    "action.decide": "Approve or roll back a simulated action",
    "enrollment.create": "Issue a one-time enrollment token for a new collector",
    "audit.read": "Read the tenant's audit log, including refused requests",
    "users.manage": "Create users, change roles, disable accounts and reset passwords",
}


def can(role: str | None, permission: str) -> bool:
    return permission in GRANTS.get(role or "", frozenset())


def permissions_of(role: str | None) -> list[str]:
    return sorted(GRANTS.get(role or "", frozenset()))


def validate_config(auth_config: dict) -> None:
    """Refuse to start with a dashboard token whose role is not one we know."""
    for key, rec in (auth_config.get("dashboard") or {}).items():
        role = rec.get("role", "viewer")
        if role not in ROLES:
            raise ValueError(f"a dashboard credential has the unknown role {role!r}; roles are {', '.join(ROLES)}")


def matrix() -> dict:
    return {"roles": {r: permissions_of(r) for r in ROLES}, "permissions": PERMISSIONS}
