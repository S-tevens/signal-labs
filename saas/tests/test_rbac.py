"""Role-based access control: the matrix, fail-closed behaviour, audit of refusals and response headers."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from saas import rbac
from saas.main import create_app
from saas.store import Store
from saas.tests.test_service import AUTH, client, db_url, get  # noqa: F401  (fixtures)

TOKENS = {"viewer": "dv", "auditor": "dau", "operator": "d1", "admin": "admin"}  # all in tenant t-one


# ---- the matrix itself (no database) ----
def test_each_role_includes_everything_the_one_below_it_can_do():
    assert rbac.GRANTS["viewer"] < rbac.GRANTS["operator"] < rbac.GRANTS["admin"]
    assert rbac.GRANTS["viewer"] < rbac.GRANTS["auditor"] < rbac.GRANTS["admin"]
    assert not rbac.GRANTS["auditor"] & {"action.propose", "action.decide", "ai.summary", "users.manage"}  # an auditor reads, never acts


def test_unknown_roles_unknown_permissions_and_no_role_get_nothing():
    assert not rbac.can("root", "read") and not rbac.can(None, "read") and not rbac.can("", "read")
    assert not rbac.can("admin", "delete.everything")
    assert rbac.permissions_of("viewer ") == []  # a stray space is not the viewer role


def test_a_misspelt_role_in_the_configuration_stops_the_service():
    with pytest.raises(ValueError, match="unknown role"):
        rbac.validate_config({"dashboard": {"k": {"tenant": "t", "region": "in", "role": "admn"}}})
    rbac.validate_config({"dashboard": {"k": {"tenant": "t", "region": "in"}}})  # no role means viewer: allowed


def test_every_permission_the_routes_ask_for_is_defined():
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    asked = set(re.findall(r"need\(request,'([a-z.]+)'\)", source))
    assert asked and asked <= set(rbac.PERMISSIONS), asked - set(rbac.PERMISSIONS)
    assert set(rbac.PERMISSIONS) == set().union(*rbac.GRANTS.values())  # no permission nobody can hold, none undocumented


def test_only_admins_can_enrol_and_only_operators_and_above_can_act():
    assert [r for r in rbac.ROLES if rbac.can(r, "enrollment.create")] == ["admin"]
    assert [r for r in rbac.ROLES if rbac.can(r, "audit.read")] == ["auditor", "admin"]
    assert [r for r in rbac.ROLES if rbac.can(r, "users.manage")] == ["admin"]
    assert [r for r in rbac.ROLES if rbac.can(r, "action.propose")] == ["operator", "admin"]
    assert [r for r in rbac.ROLES if rbac.can(r, "ai.summary")] == ["operator", "admin"]


# ---- the routes (need a test database) ----
def call(c, method, path, role, body=None):
    headers = {"Authorization": "Bearer " + TOKENS[role]}
    return c.request(method, path, headers=headers, json=body)


@pytest.mark.parametrize("method,path,body,allowed", [
    ("GET", "/v1/fleet", None, {"viewer", "auditor", "operator", "admin"}),
    ("GET", "/v1/incidents", None, {"viewer", "auditor", "operator", "admin"}),
    ("GET", "/v1/rbac", None, {"viewer", "auditor", "operator", "admin"}),
    ("POST", "/v1/actions/propose", {}, {"operator", "admin"}),
    ("POST", "/v1/actions/nope/approve", None, {"operator", "admin"}),
    ("GET", "/v1/incidents/nope/ai-summary", None, {"operator", "admin"}),
    ("POST", "/v1/enrollment-tokens", {"collector_id": "col-rbac-1"}, {"admin"}),
    ("GET", "/v1/audit", None, {"auditor", "admin"}),
    ("GET", "/v1/users", None, {"admin"}),
])
def test_each_route_allows_exactly_the_roles_in_the_matrix(client, method, path, body, allowed):
    for role in rbac.ROLES:
        status = call(client, method, path, role, body).status_code
        if role in allowed:
            assert status != 403, (role, path, status)
        else:
            assert status == 403, (role, path, status)


def test_no_credential_or_a_wrong_one_is_unauthorized_not_forbidden(client):
    assert client.get("/v1/fleet").status_code == 401
    assert get(client, "/v1/fleet", key="nobody").status_code == 401
    assert client.post("/v1/actions/propose", json={}).status_code == 401


def test_the_session_and_matrix_tell_the_dashboard_what_the_caller_may_do(client):
    s = call(client, "GET", "/v1/session", "viewer").json()
    assert s["role"] == "viewer" and s["permissions"] == ["read"]
    m = call(client, "GET", "/v1/rbac", "operator").json()
    assert m["you"]["role"] == "operator" and "action.propose" in m["you"]["permissions"] and set(m["roles"]) == set(rbac.ROLES)


def test_a_refused_request_is_audited_without_the_credential(client, db_url):
    assert call(client, "POST", "/v1/actions/propose", "viewer", {}).status_code == 403
    with Store(db_url).connect("t-one") as db:
        rows = db.execute("SELECT detail FROM audit WHERE action='access_denied'").fetchall()
    assert rows and any('"viewer"' in r["detail"] and "action.propose" in r["detail"] for r in rows)
    assert not any("dv" in r["detail"].replace("viewer", "") for r in rows)  # the token's name is not recorded


def test_the_message_says_what_the_role_cannot_do(client):
    detail = call(client, "POST", "/v1/enrollment-tokens", "operator", {"collector_id": "col-rbac-2"}).json()["detail"]
    assert "operator" in detail and "enrollment" in detail


def test_a_role_never_reaches_another_tenant(client):
    admin_view = call(client, "GET", "/v1/fleet", "admin").json()
    other = get(client, "/v1/fleet", key="d2").json()  # a viewer of tenant t-two
    assert isinstance(admin_view, list) and other == []


def test_responses_carry_protective_headers_and_api_responses_are_not_cached(client):
    h = call(client, "GET", "/v1/fleet", "viewer").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in h["content-security-policy"] and h["referrer-policy"] == "no-referrer"
    assert client.get("/healthz").headers["x-content-type-options"] == "nosniff"


def test_a_bad_role_in_the_configuration_refuses_to_start(db_url):
    bad = {**AUTH, "dashboard": {"k": {"tenant": "t-one", "region": "in", "role": "admn"}}}
    with pytest.raises(ValueError):
        create_app("in", db_url, bad)
