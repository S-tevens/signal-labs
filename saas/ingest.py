import time,json
from .store import dump,utc,epoch,count,state,audit
from .aiops import canonical,detect
from .health import metric_state,worse,RANK
from .correlation import correlate

def refresh(db,config,now=None):
    now=time.time() if now is None else now
    for row in db.execute('SELECT * FROM fleet').fetchall():
        age=max(0,now-row['last_seen']); target=row['report_state']; reason='Latest telemetry health'
        signals=db.execute('SELECT state,ts,signal,source FROM health_signals WHERE collector=?',(row['id'],)).fetchall()
        recent=[s for s in signals if now-epoch(s['ts'])<config['offline_after_s']]
        if signals:
            if recent:
                worst=max(recent,key=lambda s:(RANK[s['state']],s['ts']))
                target=worst['state']
                reason=f"{worst['signal']} from {worst['source']} reported {target} at {worst['ts']}"
                observation=db.execute('SELECT data FROM payloads WHERE collector=? AND source=? AND ts=? AND metric=? ORDER BY id LIMIT 1',(row['id'],worst['source'],worst['ts'],worst['signal'])).fetchone()
                if observation:
                    payload=json.loads(observation['data']); metric=payload.get('metric')
                    if metric and canonical(metric['name'])==worst['signal']:
                        reason+=f"; value {metric['value']} {metric['unit']}"
                        rule=config['metrics'].get(worst['signal'],{})
                        if target.lower() in rule and metric_state(metric,config)==target:
                            reason+=f" ({target} threshold {'<=' if rule.get('inverse') else '>='} {rule[target.lower()]})"
            else: target,reason='Fair','Telemetry stale: no recent signals'
        if age>=config['offline_after_s'] and not row['reason'].startswith('Collector heartbeat expired'): db.execute('INSERT INTO offline_measurements(collector,delay,ts) VALUES(?,?,?)',(row['id'],age,utc(now)))
        if age>=config['offline_after_s']: target,reason='Poor',f"Collector heartbeat expired (last seen {int(age)}s ago; offline after {config['offline_after_s']}s)"
        elif age>=config['stale_after_s']: target,reason=worse(target,'Fair'),f"Collector heartbeat stale (last seen {int(age)}s ago; stale after {config['stale_after_s']}s)"
        state(db,row['id'],target,reason,now)

def touch(db,p,reported,now):
    cid=p['collector_id']; ts=p['event_ts_utc']; row=db.execute('SELECT * FROM fleet WHERE id=?',(cid,)).fetchone()
    if not row:
        db.execute('INSERT INTO fleet(id,last_seen,version,state,report_state,reason,config_hash,resources,latest_event) VALUES(?,?,?,?,?,?,?,?,?)',(cid,now,p['collector_version'],reported,reported,'Initial telemetry',None,'{}',ts))
        db.execute('INSERT INTO health_history(collector,state,reason,ts) VALUES(?,?,?,?)',(cid,reported,'Initial telemetry',utc(now)))
    elif not row['latest_event'] or ts>=row['latest_event']:
        db.execute('UPDATE fleet SET version=?,report_state=?,latest_event=? WHERE id=?',(p['collector_version'],reported,ts,cid))

def process(db,p,config,now=None):
    now=time.time() if now is None else now; pid=p['payload_id']; metric=p.get('metric'); event=p.get('event')
    name=canonical(metric['name']) if metric else None; signal=None; report=p['health_state']
    inserted=db.execute('INSERT INTO payloads(id,collector,source,ts,received,data,metric,value) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tenant_id,id) DO NOTHING RETURNING id',(pid,p['collector_id'],p['source_id'],p['event_ts_utc'],now,dump(p),name,metric['value'] if metric else None)).fetchone()
    if not inserted:
        existing=db.execute('SELECT data FROM payloads WHERE id=?',(pid,)).fetchone()
        count(db,'duplicate_attempts'); return 'duplicate' if existing['data']==dump(p) else 'conflict'
    if metric:
        history=[r['value'] for r in db.execute('SELECT value FROM payloads WHERE collector=? AND source=? AND metric=? AND ts<? ORDER BY ts DESC LIMIT ?',(p['collector_id'],p['source_id'],name,p['event_ts_utc'],config['baseline_window']))]
        report=worse(report,metric_state(metric,config)); detected=detect(metric,history,config)
        # Update persistence only in event-time order. Late observations are stored
        # but cannot rewrite or reset the live detector's current streak.
        pending=db.execute('SELECT last_ts,consecutive FROM anomaly_pending WHERE collector=? AND source=? AND metric=?',(p['collector_id'],p['source_id'],name)).fetchone()
        if pending is None or p['event_ts_utc']>pending['last_ts']:
            streak=(pending['consecutive'] if pending else 0)+1 if detected else 0
            db.execute('INSERT INTO anomaly_pending(collector,source,metric,last_ts,consecutive) VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,collector,source,metric) DO UPDATE SET last_ts=excluded.last_ts,consecutive=excluded.consecutive',(p['collector_id'],p['source_id'],name,p['event_ts_utc'],streak))
            if detected and streak==config.get('anomaly_persistence_windows',2):
                signal={**detected,'persistence_windows':streak,'why':detected['why']+f' for {streak} consecutive windows'}
        if not signal and metric_state(metric,config)=='Poor': signal={'signal':name,'value':metric['value'],'why':f'{name} breached configured critical threshold','severity':'critical','method':'threshold fallback'}
    elif event:
        category=event['category'].lower(); failed=category in {'failed_login','auth_failure','authentication_failure','login_failure','failed_logins','auth_failed','auth_failure_burst'}
        if failed or event['severity'] in {'critical','high','error'}:
            signal={'signal':'failed_login' if failed else category,'value':event['count'],'why':f'{event["count"]} {category} event(s) in {p["window_s"]}s','severity':'critical' if event['severity'] in {'critical','high'} else 'warning','method':'local event summary'}
            report=worse(report,'Poor' if signal['severity']=='critical' else 'Fair')
    if signal: report=worse(report,'Poor' if signal['severity']=='critical' else 'Fair')
    count(db,'accepted'); touch(db,p,report,now)
    signal_key=name if metric else event['category']
    db.execute('INSERT INTO health_signals(collector,source,signal,ts,state) VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,collector,source,signal) DO UPDATE SET ts=excluded.ts,state=excluded.state WHERE excluded.ts>=health_signals.ts',(p['collector_id'],p['source_id'],signal_key,p['event_ts_utc'],report))
    if signal:
        correlate(db,p,signal,config,now)
        db.execute('INSERT INTO alert_measurements(payload_id,delay) VALUES(?,?)',(pid,max(0,now-epoch(p['event_ts_utc']))))
    return 'accepted'
