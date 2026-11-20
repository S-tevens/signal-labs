SET search_path TO signal, pg_catalog;
CREATE TABLE IF NOT EXISTS actions (
    tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true),
    id TEXT NOT NULL, incident_id TEXT NOT NULL, action_type TEXT NOT NULL,
    parameters TEXT NOT NULL, status TEXT NOT NULL, proposed_by TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, rollback_plan TEXT NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, incident_id) REFERENCES incidents(tenant_id, id)
);
CREATE INDEX IF NOT EXISTS actions_incident_idx ON actions(tenant_id,incident_id);
ALTER TABLE actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE actions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON actions;
CREATE POLICY tenant_scope ON actions
USING (tenant_id = nullif(current_setting('app.tenant_id',true),''))
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),''));
CREATE TABLE IF NOT EXISTS anomaly_pending (
    tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true),
    collector TEXT NOT NULL, source TEXT NOT NULL, metric TEXT NOT NULL,
    last_ts TEXT NOT NULL, consecutive INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, collector, source, metric)
);
ALTER TABLE anomaly_pending ENABLE ROW LEVEL SECURITY;
ALTER TABLE anomaly_pending FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_scope ON anomaly_pending;
CREATE POLICY tenant_scope ON anomaly_pending
USING (tenant_id = nullif(current_setting('app.tenant_id',true),''))
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id',true),''));
CREATE TABLE IF NOT EXISTS enrollment_tokens (
    tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true),
    token_hash TEXT NOT NULL, collector_id TEXT NOT NULL, region TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL, used_at DOUBLE PRECISION,
    PRIMARY KEY (tenant_id, token_hash)
);
CREATE TABLE IF NOT EXISTS collector_credentials (
    tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true),
    key_hash TEXT NOT NULL, collector_id TEXT NOT NULL, region TEXT NOT NULL,
    signing_secret TEXT NOT NULL, created_at TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (tenant_id, key_hash)
);
DO $$ DECLARE t text; BEGIN
FOREACH t IN ARRAY ARRAY['enrollment_tokens','collector_credentials'] LOOP
  EXECUTE format('ALTER TABLE signal.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('ALTER TABLE signal.%I FORCE ROW LEVEL SECURITY',t);
  EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON signal.%I',t);
  EXECUTE format('CREATE POLICY tenant_scope ON signal.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),''''))',t);
END LOOP; END $$;
-- One region per database. The first configured regional replica binds the database.
CREATE TABLE IF NOT EXISTS region_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    region TEXT NOT NULL
);
