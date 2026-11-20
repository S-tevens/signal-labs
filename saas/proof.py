import math, time
from .store import epoch, utc

def p95(values):
    if not values: return None
    return round(sorted(values)[math.ceil(.95*len(values))-1],4)

def proof(db, window_s=None):
    now=time.time(); start=now-window_s if window_s is not None else None
    rows=db.execute('SELECT id,ts,received FROM payloads' + (' WHERE received>=?' if start is not None else ''), (start,) if start is not None else ()).fetchall()
    counters={r['name']:r['value'] for r in db.execute('SELECT * FROM counters')}
    delays=[max(0,r['received']-epoch(r['ts'])) for r in rows]
    q='SELECT p.ts,r.rendered FROM renders r JOIN payloads p ON p.id=r.id AND p.tenant_id=r.tenant_id'
    renders=db.execute(q+(' WHERE r.rendered>=?' if start is not None else ''),(start,) if start is not None else ()).fetchall()
    q='SELECT a.delay FROM alert_measurements a JOIN payloads p ON p.id=a.payload_id AND p.tenant_id=a.tenant_id'
    alerts=[r['delay'] for r in db.execute(q+(' WHERE p.received>=?' if start is not None else ''),(start,) if start is not None else ())]
    offline=[r['delay'] for r in db.execute('SELECT delay FROM offline_measurements'+(' WHERE ts>=?' if start is not None else ''),(utc(start),) if start is not None else ())]
    return {'window_s':window_s,'window_start_utc':utc(start) if start is not None else None,'window_end_utc':utc(now),
            'received_unique':len(rows),'received_ids':[r['id'] for r in rows],
            'duplicate_attempts':counters.get('duplicate_attempts',0),'stored_duplicates':0,
            'p95_ingest_latency_s':p95(delays),'p95_dashboard_latency_s':p95([max(0,r['rendered']-epoch(r['ts'])) for r in renders]),
            'dashboard_samples':len(renders),'p95_alert_delay_s':p95(alerts),'max_alert_delay_s':round(max(alerts),4) if alerts else None,
            'offline_detection_s':round(max(offline),4) if offline else None,'sent_count':None,'lost_count':None,
            'measurement_notes':'Window filters receipt, render and offline-measurement times; duplicate_attempts is cumulative. Dashboard acknowledgements are client-reported, clock skew affects latency, and sent-ID comparison must come from the collector.'}
