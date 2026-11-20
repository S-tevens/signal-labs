import json, os, time
from datetime import datetime, timezone
from contextlib import contextmanager

def utc(epoch=None): return datetime.fromtimestamp(time.time() if epoch is None else epoch,timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
def epoch(value):
    dt=datetime.fromisoformat(value.replace('Z','+00:00'))
    if dt.tzinfo is None: raise ValueError('Timezone required')
    return dt.timestamp()
def dump(v): return json.dumps(v,separators=(',',':'),sort_keys=True,allow_nan=False)
class DB:
    def __init__(self, conn): self.conn=conn
    def execute(self, sql, params=()): return self.conn.execute(sql.replace('?', '%s'),params)
class Store:
    def __init__(self, database_url=None, region=None):
        self.url=database_url or os.getenv('DATABASE_URL','')
        self.region=region
    def check(self):
        if not self.url: raise RuntimeError('DATABASE_URL is required')
        import psycopg
        with psycopg.connect(self.url,connect_timeout=5) as db:
            role=db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if any(role): raise RuntimeError('Application role must not have superuser or BYPASSRLS privileges')
            db.execute('SELECT 1 FROM signal.payloads LIMIT 1')
            if self.region:
                db.execute('INSERT INTO signal.region_binding(singleton,region) VALUES (1,%s) ON CONFLICT(singleton) DO NOTHING',(self.region,))
                bound=db.execute('SELECT region FROM signal.region_binding WHERE singleton=1').fetchone()[0]
                if bound != self.region: raise RuntimeError('Database belongs to a different region')
    @contextmanager
    def connect(self,tenant):
        import psycopg
        from psycopg.rows import dict_row
        if not self.url: raise RuntimeError('DATABASE_URL is required')
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.transaction():
                conn.execute("SET LOCAL search_path TO signal, pg_catalog")
                conn.execute("SELECT set_config('app.tenant_id', %s, true)",(tenant,))
                # Serialize per-tenant processing across replicas, not across tenants.
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(tenant,))
                yield DB(conn)
def count(db,name,n=1): db.execute('INSERT INTO counters(name,value) VALUES(?,?) ON CONFLICT(tenant_id,name) DO UPDATE SET value=counters.value+excluded.value',(name,n))
def audit(db,action,ref,detail): db.execute('INSERT INTO audit(action,reference,ts,detail) VALUES(?,?,?,?)',(action,ref,utc(),dump(detail)))
def state(db,collector,new,reason,now):
    row=db.execute('SELECT state FROM fleet WHERE id=?',(collector,)).fetchone()
    if row and row['state']!=new:
        db.execute('UPDATE fleet SET state=?,reason=? WHERE id=?',(new,reason,collector)); db.execute('INSERT INTO health_history(collector,state,reason,ts) VALUES(?,?,?,?)',(collector,new,reason,utc(now)))
    elif row: db.execute('UPDATE fleet SET reason=? WHERE id=? AND reason IS DISTINCT FROM ?',(reason,collector,reason))
