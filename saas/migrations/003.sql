-- A commit sends only the tenant identifier; no telemetry is put on the channel.
CREATE OR REPLACE FUNCTION signal.notify_dashboard_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('signal_dashboard_updates', NEW.tenant_id);
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS dashboard_update ON signal.payloads;
CREATE TRIGGER dashboard_update AFTER INSERT ON signal.payloads
FOR EACH ROW EXECUTE FUNCTION signal.notify_dashboard_update();
DROP TRIGGER IF EXISTS dashboard_update ON signal.fleet;
CREATE TRIGGER dashboard_update AFTER INSERT OR UPDATE ON signal.fleet
FOR EACH ROW EXECUTE FUNCTION signal.notify_dashboard_update();
DROP TRIGGER IF EXISTS dashboard_update ON signal.incidents;
CREATE TRIGGER dashboard_update AFTER INSERT OR UPDATE ON signal.incidents
FOR EACH ROW EXECUTE FUNCTION signal.notify_dashboard_update();
