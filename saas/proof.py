import math,json
from .store import epoch

def p95(values):
    if not values:return None
    return round(sorted(values)[math.ceil(.95*len(values))-1],4)
def proof(db):
    rows=db.execute('SELECT id,ts,received FROM payloads').fetchall(); counters={r['name']:r['value'] for r in db.execute('SELECT * FROM counters')}
    delays=[max(0,r['received']-epoch(r['ts'])) for r in rows]
    renders=db.execute('SELECT p.ts,r.rendered FROM renders r JOIN payloads p ON p.id=r.id AND p.tenant_id=r.tenant_id').fetchall()
    alerts=[r['delay'] for r in db.execute('SELECT delay FROM alert_measurements')]; offline=[r['delay'] for r in db.execute('SELECT delay FROM offline_measurements')]
    return {'received_unique':len(rows),'received_ids':[r['id'] for r in rows],'duplicate_attempts':counters.get('duplicate_attempts',0),'stored_duplicates':0,'p95_ingest_latency_s':p95(delays),'p95_dashboard_latency_s':p95([max(0,r['rendered']-epoch(r['ts'])) for r in renders]),'dashboard_samples':len(renders),'p95_alert_delay_s':p95(alerts),'max_alert_delay_s':round(max(alerts),4) if alerts else None,'offline_detection_s':round(max(offline),4) if offline else None,'sent_count':None,'lost_count':None,'measurement_notes':'Dashboard render requires client acknowledgements; collector sent-ID comparison must be supplied by demo harness. Offline detection is measured from last heartbeat, not external outage onset.'}
