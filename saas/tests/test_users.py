"""Sign-in, sessions and user management: roles live on the server and change take effect immediately."""
import json

import pytest
from fastapi.testclient import TestClient

from saas import users
from saas.main import create_app
from saas.store import Store
from saas.tests.test_service import AUTH, db_url, get  # noqa: F401  (fixtures)

SECRET = "test-session-secret-0123456789abcdef0123456789"
GOOD = "correct horse battery"


# ---- pure parts ----
def test_passwords_are_salted_hashed_and_verified():
    a, b = users.hash_password(GOOD), users.hash_password(GOOD)
    assert a != b and GOOD not in a and a.startswith("scrypt$")
    assert users.verify_password(GOOD, a) and not users.verify_password(GOOD + "x", a) and not users.verify_password(GOOD, "garbage")


def test_password_policy_rejects_the_obvious_traps():
    assert users.password_problem("short") and users.password_problem("aaaaaaaaaaaa") and users.password_problem("Password1")
    assert users.password_problem("carolbrown2026", "carolbrown") and users.password_problem(None)
    assert users.password_problem(GOOD) is None


def test_tokens_carry_identity_only_and_reject_tampering_and_expiry():
    token, exp = users.issue_token(SECRET, "t-one", "bob", 3, ttl=60, now=1000)
    claims = users.read_token(SECRET, token, now=1010)
    assert claims == {"t": "t-one", "u": "bob", "v": 3, "iat": 1000, "exp": 1060} and "role" not in claims
    assert users.read_token(SECRET, token, now=1061) is None
    assert users.read_token("another-secret-another-secret-another", token, now=1010) is None
    body, sig = token[4:].split(".")
    assert users.read_token(SECRET, "sl1." + body[:-2] + "AA." + sig, now=1010) is None
    assert users.read_token(SECRET, "garbage") is None and users.read_token(SECRET, "sl1." + "x" * 700) is None


# ---- the platform ----
@pytest.fixture
def app_client(db_url, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SAAS_SESSION_SECRET", SECRET)
    with Store(db_url).connect("t-one") as db:
        db.execute("DELETE FROM users")
    with Store(db_url).connect("t-two") as db:
        db.execute("DELETE FROM users")
    with TestClient(create_app("in", db_url, AUTH)) as c:
        yield c


def api(c, method, path, token=None, body=None):
    return c.request(method, path, headers={"Authorization": "Bearer " + token} if token else {}, json=body)


def sign_in(c, username, password, tenant="t-one"):
    return c.post("/v1/login", json={"tenant": tenant, "username": username, "password": password})


def make_user(c, username, role, password=GOOD, tenant_token="admin"):
    r = api(c, "POST", "/v1/users", tenant_token, {"username": username, "display_name": username.title(), "role": role, "temporary_password": password})
    assert r.status_code == 200, r.text
    return r.json()


def ready_user(c, username, role):
    """A user who has already replaced the temporary password; returns their session token."""
    make_user(c, username, role)
    first = sign_in(c, username, GOOD).json()["token"]
    r = api(c, "POST", "/v1/me/password", first, {"current_password": GOOD, "new_password": "a better passphrase 42"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_a_new_user_must_replace_the_temporary_password_before_anything_else(app_client):
    make_user(app_client, "bob", "viewer")
    token = sign_in(app_client, "bob", GOOD).json()["token"]
    session = api(app_client, "GET", "/v1/session", token).json()
    assert session["must_change_password"] is True and session["permissions"] == [] and session["user"] == "bob"
    blocked = api(app_client, "GET", "/v1/fleet", token)
    assert blocked.status_code == 403 and "temporary password" in blocked.json()["detail"]
    assert api(app_client, "POST", "/v1/me/password", token, {"current_password": GOOD, "new_password": "short"}).status_code == 422
    new = ready_user(app_client, "carol", "viewer")
    assert api(app_client, "GET", "/v1/fleet", new).status_code == 200  # after the change, normal access


def test_a_role_change_applies_to_the_same_token_immediately(app_client):
    token = ready_user(app_client, "dana", "viewer")
    assert api(app_client, "POST", "/v1/actions/propose", token, {}).status_code == 403
    r = api(app_client, "PATCH", "/v1/users/dana", "admin", {"role": "operator"})
    assert r.status_code == 200 and r.json()["role"] == "operator"
    assert api(app_client, "POST", "/v1/actions/propose", token, {}).status_code != 403  # no new sign-in needed
    api(app_client, "PATCH", "/v1/users/dana", "admin", {"role": "viewer"})
    assert api(app_client, "POST", "/v1/actions/propose", token, {}).status_code == 403  # and it takes back just as fast


def test_disabling_a_user_ends_their_session_and_blocks_sign_in(app_client):
    token = ready_user(app_client, "erin", "operator")
    assert api(app_client, "GET", "/v1/fleet", token).status_code == 200
    assert api(app_client, "PATCH", "/v1/users/erin", "admin", {"active": False}).status_code == 200
    assert api(app_client, "GET", "/v1/fleet", token).status_code == 401
    assert sign_in(app_client, "erin", "a better passphrase 42").status_code == 401
    api(app_client, "PATCH", "/v1/users/erin", "admin", {"active": True})
    assert sign_in(app_client, "erin", "a better passphrase 42").status_code == 200


def test_logout_revokes_the_session(app_client):
    token = ready_user(app_client, "finn", "viewer")
    assert api(app_client, "POST", "/v1/logout", token).status_code == 200
    assert api(app_client, "GET", "/v1/fleet", token).status_code == 401


def test_a_password_reset_signs_the_user_out_everywhere_and_demands_a_new_one(app_client):
    token = ready_user(app_client, "gwen", "viewer")
    assert api(app_client, "POST", "/v1/users/gwen/password", "admin", {"temporary_password": "another temporary phrase"}).status_code == 200
    assert api(app_client, "GET", "/v1/fleet", token).status_code == 401
    session = api(app_client, "GET", "/v1/session", sign_in(app_client, "gwen", "another temporary phrase").json()["token"]).json()
    assert session["must_change_password"] is True


def test_five_wrong_passwords_lock_the_account_until_an_admin_resets_it(app_client):
    make_user(app_client, "hana", "viewer")
    for _ in range(5):
        assert sign_in(app_client, "hana", "wrong password here").status_code == 401
    locked = sign_in(app_client, "hana", GOOD)  # even the right password is refused while locked
    assert locked.status_code == 429 and "administrator" in locked.json()["detail"]
    api(app_client, "POST", "/v1/users/hana/password", "admin", {"temporary_password": "fresh temporary phrase"})
    assert sign_in(app_client, "hana", "fresh temporary phrase").status_code == 200


def test_sign_in_does_not_reveal_whether_a_user_exists(app_client):
    make_user(app_client, "ivan", "viewer")
    wrong, unknown = sign_in(app_client, "ivan", "not the password"), sign_in(app_client, "nobody.here", "not the password")
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    assert sign_in(app_client, "ivan", GOOD, tenant="not-a-tenant").status_code == 401


def test_the_last_active_administrator_cannot_be_demoted_or_disabled(app_client):
    make_user(app_client, "judy", "admin")
    assert api(app_client, "PATCH", "/v1/users/judy", "admin", {"role": "viewer"}).status_code == 409
    assert api(app_client, "PATCH", "/v1/users/judy", "admin", {"active": False}).status_code == 409
    make_user(app_client, "karl", "admin")
    assert api(app_client, "PATCH", "/v1/users/judy", "admin", {"role": "viewer"}).status_code == 200


def test_an_admin_cannot_disable_their_own_account(app_client):
    token = ready_user(app_client, "lena", "admin")
    make_user(app_client, "mike", "admin")
    assert api(app_client, "PATCH", "/v1/users/lena", token, {"active": False}).status_code == 409


def test_only_admins_manage_users_and_input_is_validated(app_client):
    viewer = ready_user(app_client, "nora", "viewer")
    operator = ready_user(app_client, "otto", "operator")
    for t in (viewer, operator):
        assert api(app_client, "GET", "/v1/users", t).status_code == 403
        assert api(app_client, "POST", "/v1/users", t, {}).status_code == 403
    assert api(app_client, "POST", "/v1/users", "admin", {"username": "Bad Name!", "display_name": "x", "role": "viewer", "temporary_password": GOOD}).status_code == 422
    assert api(app_client, "POST", "/v1/users", "admin", {"username": "pam", "display_name": "Pam", "role": "root", "temporary_password": GOOD}).status_code == 422
    assert api(app_client, "POST", "/v1/users", "admin", {"username": "pam", "display_name": "Pam", "role": "viewer", "temporary_password": "short"}).status_code == 422
    make_user(app_client, "quin", "viewer")
    assert api(app_client, "POST", "/v1/users", "admin", {"username": "quin", "display_name": "Q", "role": "viewer", "temporary_password": GOOD}).status_code == 409
    listing = api(app_client, "GET", "/v1/users", "admin").json()
    assert all("scrypt" not in json.dumps(u) and "password_hash" not in u and GOOD not in json.dumps(u) for u in listing)


def test_users_belong_to_one_tenant(app_client):
    ready_user(app_client, "rosa", "viewer")
    assert sign_in(app_client, "rosa", "a better passphrase 42", tenant="t-two").status_code == 401


def test_the_audit_log_names_who_did_what_and_never_holds_a_password(app_client, db_url):
    make_user(app_client, "sam", "viewer")
    sign_in(app_client, "sam", "wrong password here")
    sign_in(app_client, "sam", GOOD)
    api(app_client, "PATCH", "/v1/users/sam", "admin", {"role": "operator"})
    log = api(app_client, "GET", "/v1/audit?limit=200", "admin").json()
    actions = {r["action"] for r in log}
    assert {"user_created", "login_failed", "login_success", "user_role_changed"} <= actions
    changed = next(r for r in log if r["action"] == "user_role_changed")
    assert changed["detail"]["role_from"] == "viewer" and changed["detail"]["role_to"] == "operator" and changed["detail"]["actor"] == "api-token"
    assert GOOD not in json.dumps(log) and "wrong password" not in json.dumps(log)


def test_the_api_tokens_still_work_for_scripts_and_can_be_switched_off(db_url, monkeypatch):
    monkeypatch.setenv("SAAS_SESSION_SECRET", SECRET)
    with TestClient(create_app("in", db_url, AUTH)) as c:
        assert get(c, "/v1/fleet", key="d1").status_code == 200
        assert get(c, "/v1/session", key="d1").json()["auth"] == "api-token"
    monkeypatch.setenv("SAAS_DISABLE_API_TOKENS", "1")
    with TestClient(create_app("in", db_url, AUTH)) as c:
        assert get(c, "/v1/fleet", key="d1").status_code == 401


def test_sign_in_is_unavailable_without_a_session_secret(db_url, monkeypatch):
    monkeypatch.delenv("SAAS_SESSION_SECRET", raising=False)
    with TestClient(create_app("in", db_url, AUTH)) as c:
        assert sign_in(c, "anyone", GOOD).status_code == 503
