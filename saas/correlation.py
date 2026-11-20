import uuid
from .store import dump,epoch
from .aiops import recommendation
import json

def correlate(db,p,signal,config,now):
    ts=p['event_ts_utc']; window=config['correlation_window_s']; t=epoch(ts)
    rows=db.execute('SELECT * FROM incidents WHERE collector=? AND source=? ORDER BY last_ts DESC LIMIT 100',(p['collector_id'],p['source_id'])).fetchall()
    # Same source and event-time window. A real topology graph is a future extension.
    row=next((r for r in rows if epoch(r['first_ts'])-window<=t<=epoch(r['last_ts'])+window),None)
    if row: incident=json.loads(row['data'])
    else: incident={'id':str(uuid.uuid4()),'collector_id':p['collector_id'],'source_id':p['source_id'],'first_ts':ts,'last_ts':ts,'signals':[],'status':'open','severity':'warning','alert_count':0,'created_at_epoch':now}
    incident['first_ts']=min(incident['first_ts'],ts); incident['last_ts']=max(incident['last_ts'],ts)
    signal={**signal,'payload_id':p['payload_id'],'event_ts_utc':ts,'alert_delay_s':max(0,now-t)}
    incident['alert_count']+=1; incident['signals']=(incident['signals']+[signal])[-100:]; incident['signals'].sort(key=lambda s:s['event_ts_utc'])
    if signal['severity']=='critical': incident['severity']='critical'
    incident['recommendation']=recommendation(incident['signals'])
    db.execute('INSERT INTO incidents(id,collector,source,first_ts,last_ts,created,data) VALUES(?,?,?,?,?,?,?) ON CONFLICT(tenant_id,id) DO UPDATE SET first_ts=excluded.first_ts,last_ts=excluded.last_ts,data=excluded.data',(incident['id'],p['collector_id'],p['source_id'],incident['first_ts'],incident['last_ts'],incident['created_at_epoch'],dump(incident)))
    return incident
