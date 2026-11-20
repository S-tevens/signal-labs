CREATE SCHEMA IF NOT EXISTS signal;
SET search_path TO signal, pg_catalog;
CREATE TABLE IF NOT EXISTS payloads(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id TEXT NOT NULL, collector TEXT NOT NULL, source TEXT NOT NULL, ts TEXT NOT NULL, received DOUBLE PRECISION NOT NULL, data TEXT NOT NULL, metric TEXT, value DOUBLE PRECISION, PRIMARY KEY(tenant_id,id));
CREATE INDEX IF NOT EXISTS metric_idx ON payloads(tenant_id,collector,source,metric,ts);
CREATE TABLE IF NOT EXISTS fleet(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id TEXT NOT NULL, last_seen DOUBLE PRECISION NOT NULL, version TEXT, state TEXT NOT NULL, report_state TEXT NOT NULL, reason TEXT, config_hash TEXT, resources TEXT, latest_event TEXT, PRIMARY KEY(tenant_id,id));
CREATE TABLE IF NOT EXISTS health_history(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id BIGINT GENERATED ALWAYS AS IDENTITY, collector TEXT,state TEXT,reason TEXT,ts TEXT, PRIMARY KEY(tenant_id,id));
CREATE TABLE IF NOT EXISTS incidents(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id TEXT NOT NULL,collector TEXT,source TEXT,first_ts TEXT,last_ts TEXT,created DOUBLE PRECISION,data TEXT, PRIMARY KEY(tenant_id,id));
CREATE INDEX IF NOT EXISTS incident_idx ON incidents(tenant_id,collector,source,last_ts);
CREATE TABLE IF NOT EXISTS audit(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id BIGINT GENERATED ALWAYS AS IDENTITY,action TEXT,reference TEXT,ts TEXT,detail TEXT, PRIMARY KEY(tenant_id,id));
CREATE TABLE IF NOT EXISTS health_signals(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), collector TEXT,source TEXT,signal TEXT,ts TEXT,state TEXT,PRIMARY KEY(tenant_id,collector,source,signal));
CREATE TABLE IF NOT EXISTS offline_measurements(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), collector TEXT,delay DOUBLE PRECISION,ts TEXT);
CREATE TABLE IF NOT EXISTS alert_measurements(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), payload_id TEXT,delay DOUBLE PRECISION,PRIMARY KEY(tenant_id,payload_id));
CREATE TABLE IF NOT EXISTS renders(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), id TEXT,rendered DOUBLE PRECISION NOT NULL,PRIMARY KEY(tenant_id,id));
CREATE TABLE IF NOT EXISTS counters(tenant_id TEXT NOT NULL DEFAULT current_setting('app.tenant_id',true), name TEXT,value BIGINT NOT NULL,PRIMARY KEY(tenant_id,name));
DO $$ DECLARE t text; BEGIN
FOREACH t IN ARRAY ARRAY['payloads','fleet','health_history','incidents','audit','health_signals','offline_measurements','alert_measurements','renders','counters'] LOOP
EXECUTE format('ALTER TABLE signal.%I ENABLE ROW LEVEL SECURITY',t);
EXECUTE format('ALTER TABLE signal.%I FORCE ROW LEVEL SECURITY',t);
EXECUTE format('DROP POLICY IF EXISTS tenant_scope ON signal.%I',t);
EXECUTE format('CREATE POLICY tenant_scope ON signal.%I USING (tenant_id = nullif(current_setting(''app.tenant_id'',true),'''')) WITH CHECK (tenant_id = nullif(current_setting(''app.tenant_id'',true),''''))',t);
END LOOP; END $$;
