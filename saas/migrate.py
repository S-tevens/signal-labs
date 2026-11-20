"""Run once with an administrative connection; replicas use only DATABASE_URL."""
import os
from pathlib import Path

def main():
    import psycopg
    from psycopg import sql
    admin=os.environ['ADMIN_DATABASE_URL']; password=os.environ['SAAS_DB_PASSWORD']
    if not password: raise ValueError('SAAS_DB_PASSWORD must not be empty')
    role=os.getenv('SAAS_DB_USER','signal_app'); ident=sql.Identifier(role)
    with psycopg.connect(admin) as db:
        db.execute("SELECT pg_advisory_xact_lock(7209331)")
        existing=db.execute('SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
        if existing and any(existing): raise RuntimeError('Refusing privileged application role')
        if not existing: db.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOINHERIT PASSWORD {}').format(ident,sql.Literal(password)))
        else: db.execute(sql.SQL('ALTER ROLE {} LOGIN PASSWORD {}').format(ident,sql.Literal(password)))
        for f in sorted((Path(__file__).parent/'migrations').glob('*.sql')): db.execute(f.read_text(),prepare=False)
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA signal TO {}').format(ident))
        db.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA signal TO {}').format(ident))
        db.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA signal TO {}').format(ident))
    print('Signal Labs schema initialized')
if __name__=='__main__': main()
