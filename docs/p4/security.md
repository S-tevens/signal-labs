# Security: data protection, secure communication and controlled access

How Signal Labs meets the criterion "robust security features to ensure data protection, secure communication, and controlled access (role-based action control)", what proves each claim, and what is not done. Every command below is runnable from the repository root.

## 1. Data protection

| Control | How it works | Proof |
|---|---|---|
| Raw data never leaves the customer | The collector keeps raw records in its own store and sends only metadata that passes a fixed allow-list schema and the customer's own policy. Free text cannot travel in any payload (summaries are templates) | `.\scripts\demo.ps1 secret`, then `.\scripts\verify.ps1`: planted secrets are found in the collector's local store and nowhere on the platform (egress log, API, every database table for all tenants, logs) |
| Redaction and pseudonyms | Rule-based detection of passwords, tokens, keys, emails and addresses; hosts become keyed pseudonymous source IDs | The egress panel shows the raw record beside the payload with a leak check |
| Local views stay local | The collector's raw views answer only this machine; hold and release also need the local page's header | Tests in `collector/tests` (remote requests get 403) |
| Tenant isolation in storage | Every row carries its tenant and row-level security applies in Postgres; the tenant comes from the credential, never the payload | `.\scripts\demo.ps1 tenants` (13 checks) |
| The AI provider sees little | Gemini receives only allow-listed incident metadata: no raw logs, hostnames, or source, collector or payload IDs. Only operators and admins can trigger it, and it is rate limited | `saas/llm.py`, `saas/tests/test_llm.py` |
| Evidence is checked for credentials | `.\scripts\bundle-evidence.ps1` refuses to build if any file looks like a credential, including Google keys | The script itself |

## 2. Secure communication

| Control | How it works | Proof |
|---|---|---|
| Encrypted and verified | Collector to SaaS over TLS 1.2 or later. The collector verifies the server certificate and name against a pinned private CA; there is no switch to turn verification off | `.\scripts\demo.ps1 tls`; a certificate from another authority is refused |
| Authenticated and tamper-evident | Every batch carries an HMAC-SHA256 signature over the exact bytes, keyed per collector | The platform rejects a wrong signature with 401 |
| Safe retries | Payloads have unique IDs; a repeated ID is absorbed and the same ID with a different body is reported as a conflict | `.\scripts\demo.ps1 delivery` |
| Enrollment | One-time, expiring tokens; credentials are stored owner-only on the collector | `.\scripts\demo.ps1 enroll` |
| Protective headers | Every platform response carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `default-src 'none'` content security policy. API responses are `no-store`. HSTS is added over HTTPS | The `rbac` scenario and `saas/tests/test_rbac.py` |
| Strict page security | The collector's local page builds all content from text nodes and runs under a strict content security policy | A test fails if the page ever uses `innerHTML` |

## 3. Controlled access: role-based action control

One permission matrix (`saas/rbac.py`) that every dashboard route goes through, and real users who hold the roles.

| Permission | What it allows | viewer | auditor | operator | admin |
|---|---|:-:|:-:|:-:|:-:|
| `read` | See the fleet, metrics, incidents, evidence, lineage and proof for the tenant | yes | yes | yes | yes |
| `audit.read` | Read the tenant's audit log, including refused requests | | yes | | yes |
| `ai.summary` | Ask for an AI-written incident summary | | | yes | yes |
| `action.propose` | Propose a simulated remediation action | | | yes | yes |
| `action.decide` | Approve, reject or roll back a simulated action | | | yes | yes |
| `enrollment.create` | Issue a one-time collector enrollment token | | | | yes |
| `users.manage` | Create users, change roles, disable accounts, reset passwords | | | | yes |

**Who holds a role.** People sign in with an organization, a username and a password. The platform returns a short-lived signed session token (one hour) that says only who they are. Their role is read from the users table on every request, so an administrator changing a role, disabling an account or resetting a password applies on the person's very next action, with no new token and no restart.

- **Passwords** are hashed with scrypt and a random salt; they are never stored, logged or returned. A new or reset account has a temporary password that allows nothing except choosing a new one.
- **Sign-in** answers identically for an unknown user and a wrong password, and does the same work either way. Five wrong passwords lock the account for five minutes (the counter is in the database, so it holds across replicas); an administrator's reset unlocks it.
- **Sessions** end on sign-out, on a password change or reset, when the account is disabled, and after an hour.
- **Guard rails.** The last active administrator cannot be demoted or disabled, and nobody can disable their own account.
- **Everything is audited with a name**: sign-ins, failures, lockouts, user creation, role changes (from and to), resets and refused requests, each with the actor.
- **API tokens** (the old static tokens) still work for scripts and the measurement tools. Set `SAAS_DISABLE_API_TOKENS=1` to switch them off.
- **Admin screen.** Users in the dashboard: add a person, change a role from a dropdown, disable or enable, reset a password, with a plain description of each role.

Rules:
- **Fail closed.** Unknown roles, missing roles and unknown permissions get nothing. A misspelt role in the configuration stops the service at start. A token with no role is a viewer (least privilege).
- **Tenant from the token.** A role never reaches another tenant: the tenant is fixed by the credential.
- **Collectors are separate principals.** Signed requests to ingest and heartbeat only; they hold no dashboard role.
- **Accountability.** Every refused request is written to the audit log with the role, the permission, the method and the path, never the credential. Admins read it at `GET /v1/audit`. Actions and approvals are audited too, and marked simulation only.
- **The dashboard explains.** It shows the signed-in role and disables, with a reason, any button the role cannot use. The platform enforces the rule regardless: hiding a button is a convenience, not the control.
- **Defence in depth.** The action and enrollment modules still check the role themselves.

Prove it: `.\scripts\demo.ps1 rbac` runs 28 checks against the live platform with real sign-ins: each role's boundaries, a role changed live (the same session is allowed at once, and refused again just as fast after demoting), a throwaway account that is locked out and reset, a disabled user's session ending, the last-administrator guard, and the audit log naming who did what with no password in it. Development sign-ins (one per role, plus a second organization) are generated by `scripts\run-local.ps1` into `data\dev-users.txt`, which is git-ignored. Platform tests: `saas/tests/test_rbac.py` and `saas/tests/test_users.py` (34 tests against a real database).

## 4. What is not done

- **No single sign-on.** Users and passwords live in the platform's own database. A real deployment would sign people in through the company's identity provider (OIDC) and map its groups to these roles; the matrix, the audit trail and the per-request role lookup carry over unchanged. There is also no multi-factor authentication, no self-service password reset by email, and no password history.
- **Session tokens are not individually revocable** (they end on sign-out, password change, disable or expiry, which covers every session of that person). They are kept in the browser tab's session storage, not an HTTP-only cookie.
- **Account lockout can be abused** to lock a known person out for five minutes. There is no per-address throttling, because behind the failover proxy every request shares one address.
- **No separation of duties.** An operator can approve their own proposal. A two-person rule would be a small addition.
- **Static API tokens exist for scripts** and are on by default in development. Switch them off with `SAAS_DISABLE_API_TOKENS=1`.
- **No replay window on signed batches.** Replays are harmless because payload IDs are idempotent, but the signature carries no timestamp or nonce.
- **Development certificates.** The private CA and dev credentials are for local demos only; never reuse them.
- **Redaction is rule-based** and can miss a secret in a format it does not know. The allow-list, not the redaction, is the guarantee: free text cannot travel.
- **The AI provider is external.** The metadata sent is minimal and labelled, but it does leave the platform. Rotate the key after the event; it is held in a git-ignored file and the environment, never in the repository or evidence.
- **Single-machine deployment**, no network segmentation, no hardware key storage.
