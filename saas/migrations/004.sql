-- Real users: the role lives here, so an administrator can change it and it takes effect on the next request.
CREATE TABLE IF NOT EXISTS users (
    tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true),
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('viewer','auditor','operator','admin')),
    password_hash TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    token_version INTEGER NOT NULL DEFAULT 0,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until DOUBLE PRECISION,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login TEXT,
    PRIMARY KEY (tenant_id, username)
);
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON users;
CREATE POLICY tenant_scope ON users USING (tenant_id = nullif(current_setting('app.tenant_id',true),'')) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),''));
