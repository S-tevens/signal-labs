import os, threading
import pytest

URL = os.getenv('TEST_DATABASE_URL')


@pytest.mark.skipif(not URL, reason='TEST_DATABASE_URL not set')
def test_read_connection_does_not_wait_for_tenant_lock():
    import psycopg
    from saas.store import Store
    store = Store(URL)
    with psycopg.connect(URL, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(hashtextextended('t-one',0))")
        try:
            got = {}
            def read():
                with store.connect('t-one', lock='try') as db: got['try'] = db.locked
                with store.connect('t-one', lock=False) as db: got['none'] = db.locked
            t = threading.Thread(target=read); t.start(); t.join(5)
            assert not t.is_alive(), 'read connection blocked on the tenant lock'
            assert got == {'try': False, 'none': False}
        finally:
            holder.execute("SELECT pg_advisory_unlock(hashtextextended('t-one',0))")
