"""Database events are emitted after commit and never include telemetry."""
import psycopg
from fastapi.testclient import TestClient
from saas.main import create_app
from saas.store import Store
from saas.tests.test_service import AUTH, db_url, p, post


def test_notification_is_committed_and_tenant_scoped(db_url):
    with TestClient(create_app('in',db_url,AUTH)) as client:
        with psycopg.connect(db_url,autocommit=True) as listener:
            listener.execute('LISTEN signal_dashboard_updates')
            assert post(client,p('notification')).status_code == 200
            notes=list(listener.notifies(timeout=2,stop_after=1))
            assert len(notes) == 1 and notes[0].payload == 't-one'


def test_rollback_does_not_emit_notification(db_url):
    with psycopg.connect(db_url,autocommit=True) as listener:
        listener.execute('LISTEN signal_dashboard_updates')
        try:
            with Store(db_url).connect('t-one') as db:
                db.execute("INSERT INTO fleet(id,last_seen,version,state,report_state,reason,config_hash,resources,latest_event) VALUES (?,?,?,?,?,?,?,?,?)",('rolled-back',1,'1','Good','Good','test',None,'{}',None))
                raise ValueError('roll back')
        except ValueError: pass
        assert not list(listener.notifies(timeout=.2,stop_after=1))
