import asyncio, json, os, time, logging, gzip, io
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
import yaml
from .schema import Payload,Heartbeat
from .auth import Auth
from .store import Store,utc,epoch,dump,state
from .ingest import process,refresh
from .llm import Engine
from .proof import proof
from .contract import validate_contract
from .ontology import REGISTRY, list_objects, object_detail, incident_lineage, payload_lineage
from .actions import TYPES, list_actions, propose, get_action, transition
from .enroll import create_token, enroll

def create_app(region=None,database_url=None,auth_config=None,thresholds=None,replica_id=None):
    region=region or os.getenv('REGION','in'); store=Store(database_url,region); auth=Auth(region,auth_config,store); replica_id=replica_id or os.getenv('REPLICA_ID','1')
    config=thresholds or yaml.safe_load((Path(__file__).parent/'config/thresholds.yaml').read_text())
    tenants={r['tenant'] for group in ('collectors','dashboard') for r in auth.config.get(group,{}).values() if r['region']==region}
    async def watchdog():
        while True:
            for tenant in tenants:
                def run(t=tenant):
                    with store.connect(t) as db: refresh(db,config)
                try: await asyncio.to_thread(run)
                except Exception: logging.exception("Watchdog database operation failed")
            await asyncio.sleep(1)
    # Each replica listens to committed database changes, then wakes only streams
    # for the affected tenant. A periodic snapshot covers listener reconnects.
    condition=asyncio.Condition(); versions={}; listener_ready=asyncio.Event()
    async def listen_updates():
        # psycopg's async mode cannot run on Windows' default event loop (it raises InterfaceError, so a replica never
        # became ready there). The blocking listener therefore runs in a thread and hands each notification to the loop.
        import psycopg, threading
        loop=asyncio.get_running_loop(); stop=threading.Event()
        async def bump(tenant):
            async with condition:
                versions[tenant]=versions.get(tenant,0)+1
                condition.notify_all()
        def run():
            while not stop.is_set():
                try:
                    with psycopg.connect(store.url,autocommit=True,connect_timeout=5) as conn:
                        conn.execute('LISTEN signal_dashboard_updates')
                        loop.call_soon_threadsafe(listener_ready.set)
                        while not stop.is_set():
                            for notification in conn.notifies(timeout=1.0):
                                asyncio.run_coroutine_threadsafe(bump(notification.payload),loop)
                except Exception:
                    logging.exception('Dashboard notification listener disconnected; reconnecting')
                    stop.wait(2)
        threading.Thread(target=run,daemon=True,name='dashboard-listener').start()
        try: await asyncio.Event().wait()
        finally: stop.set()
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.check)
        tasks=[asyncio.create_task(watchdog()),asyncio.create_task(listen_updates())]
        try:
            await asyncio.wait_for(listener_ready.wait(),timeout=8)
            yield
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    app=FastAPI(title='Secure AIOps SaaS',lifespan=lifespan)
    origins=os.getenv('DASHBOARD_ORIGINS','http://localhost:5173').split(',')
    app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST'],allow_headers=['Authorization','Content-Type'])
    async def body(request):
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>1024*1024: raise HTTPException(413,'Payload too large')
        try:
            encoding=request.headers.get("Content-Encoding","identity").lower()
            if encoding not in {"identity","gzip"}: raise HTTPException(415,"Unsupported content encoding")
            if encoding=="gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f: decoded=f.read(1024*1024+1)
                if len(decoded)>1024*1024: raise HTTPException(413,"Decompressed payload too large")
            else: decoded=raw
            parsed=json.loads(decoded)
        except (ValueError,UnicodeError,OSError,EOFError): raise HTTPException(400,'Invalid JSON')
        return bytes(raw),parsed
    def validate(model,obj):
        try:return model.model_validate(obj).model_dump(exclude_none=True)
        except ValidationError: raise HTTPException(422,'Payload does not match metadata allow-list')
    @app.get('/healthz')
    def healthz():
        try: store.check()
        except Exception: raise HTTPException(503,'Database unavailable')
        return {'status':'ok','region':region,'replica_id':replica_id}
    @app.post('/v1/enrollment-tokens')
    async def enrollment_token(request:Request):
        who=auth.dashboard(request); _,data=await body(request)
        with store.connect(who.tenant) as db: result=create_token(db,who,data)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    @app.post('/v1/enroll')
    async def enrollment(request:Request):
        _,data=await body(request)
        result=await asyncio.to_thread(enroll,store,region,data)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
    @app.post('/v1/ingest')
    async def ingest(request:Request):
        raw,obj=await body(request); who=auth.collector(request,raw); items=obj if isinstance(obj,list) else [obj]
        if not 1<=len(items)<=500: raise HTTPException(422,'Batch must contain 1–500 payloads')
        payloads=[validate(Payload,validate_contract(item)) for item in items]
        for p in payloads:
            if (p['tenant_ref'],p['collector_id'],p['region'])!=(who.tenant,who.collector,region): raise HTTPException(403,'Identity mismatch')
            if epoch(p['event_ts_utc'])>time.time()+60: raise HTTPException(422,'Event timestamp in future')
        def work():
            result={'accepted':[],'duplicate':[],'conflict':[]}
            with store.connect(who.tenant) as db:
                for p in sorted(payloads,key=lambda p:p['event_ts_utc']): result[process(db,p,config)].append(p['payload_id'])
                refresh(db,config)
            return result
        return await asyncio.to_thread(work)
    @app.post('/v1/heartbeat')
    async def heartbeat(request:Request):
        raw,obj=await body(request); who=auth.collector(request,raw); h=validate(Heartbeat,obj)
        if h['collector_id']!=who.collector: raise HTTPException(403,'Identity mismatch')
        def work():
            now=time.time()
            with store.connect(who.tenant) as db:
                row=db.execute('SELECT * FROM fleet WHERE id=?',(who.collector,)).fetchone()
                if not row:
                    db.execute('INSERT INTO fleet(id,last_seen,version,state,report_state,reason,config_hash,resources,latest_event) VALUES(?,?,?,?,?,?,?,?,?)',(who.collector,now,h['collector_version'],'Good','Good','Awaiting telemetry',h['config_hash'],dump(h['resource_usage']),None)); db.execute('INSERT INTO health_history(collector,state,reason,ts) VALUES(?,?,?,?)',(who.collector,'Good','First heartbeat',utc(now)))
                else: db.execute('UPDATE fleet SET last_seen=?,version=?,config_hash=?,resources=? WHERE id=?',(now,h['collector_version'],h['config_hash'],dump(h['resource_usage']),who.collector))
                refresh(db,config,now)
            return {'accepted':True,'server_ts_utc':utc(now)}
        return await asyncio.to_thread(work)
    @app.get('/v1/fleet')
    def fleet(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:
            refresh(db,config); return [{**{k:v for k,v in r.items() if k!="tenant_id"},'collector_id':r['id'],'last_seen_utc':utc(r['last_seen']),'resources':json.loads(r['resources']),'online':time.time()-r['last_seen']<config['offline_after_s']} for r in db.execute('SELECT * FROM fleet ORDER BY id')]
    @app.get('/v1/session')
    def session(request:Request):
        who=auth.dashboard(request)
        return {'tenant_id':who.tenant,'region':who.region,'role':who.role}
    @app.get('/v1/health/thresholds')
    def health_thresholds(request:Request):
        auth.dashboard(request)
        return {k:config[k] for k in ('metrics','stale_after_s','offline_after_s','baseline_min','baseline_window','anomaly_persistence_windows') if k in config}
    @app.get('/v1/system/status')
    def system_status(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:
            collectors=db.execute('SELECT COUNT(*) AS n FROM fleet').fetchone()['n']
            payloads=db.execute('SELECT COUNT(*) AS n FROM payloads').fetchone()['n']
            incidents=db.execute('SELECT COUNT(*) AS n FROM incidents').fetchone()['n']
        return {'tenant_id':who.tenant,'region':region,'replica_id':replica_id,'database':'reachable','collectors':collectors,'payloads':payloads,'incidents':incidents}
    @app.get('/v1/metrics')
    def metrics(request:Request,source:str|None=None,name:str|None=None,limit:int=1000):
        who=auth.dashboard(request); q='SELECT data,received FROM payloads WHERE metric IS NOT NULL'; args=[]
        from .aiops import canonical
        for field,val in [('source',source),('metric',canonical(name) if name else None)]:
            if val is not None: q+=f' AND {field}=?'; args.append(val)
        for key,op in [('from','>='),('to','<=')]:
            if key in request.query_params:
                try: val=utc(epoch(request.query_params[key]))
                except ValueError: raise HTTPException(422,'Invalid timestamp')
                q+=f' AND ts{op}?'; args.append(val)
        with store.connect(who.tenant) as db: return [{**json.loads(r['data']),'received_ts_utc':utc(r['received'])} for r in db.execute(q+' ORDER BY ts,id LIMIT ?',(*args,max(1,min(limit,10000))))]
    @app.get('/v1/incidents')
    def incidents(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return [json.loads(r['data']) for r in db.execute('SELECT data FROM incidents ORDER BY last_ts DESC')]
    @app.get('/v1/health/history')
    def history(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return [{k:v for k,v in r.items() if k!="tenant_id"} for r in db.execute('SELECT * FROM health_history ORDER BY id DESC LIMIT 1000')]
    @app.get('/v1/proof')
    def evidence(request:Request,window_s:int|None=None):
        who=auth.dashboard(request)
        if window_s is not None and not 60<=window_s<=86400: raise HTTPException(422,'window_s must be between 60 and 86400')
        with store.connect(who.tenant) as db:return proof(db,window_s)
    @app.post('/v1/proof/render')
    def render(request:Request,payload_id:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:
            if not db.execute('SELECT id FROM payloads WHERE id=?',(payload_id,)).fetchone(): raise HTTPException(404,'Unknown payload')
            db.execute('INSERT INTO renders(id,rendered) VALUES(?,?) ON CONFLICT(tenant_id,id) DO NOTHING',(payload_id,time.time()))
        return {'acknowledged':True}
    @app.post('/v1/remediation/{id}/approve')
    def remediation(request:Request,id:str):
        auth.dashboard(request)
        raise HTTPException(410,'Use the simulated action proposal and approval lifecycle')
    @app.get('/v1/ontology')
    def ontology(request:Request):
        auth.dashboard(request)
        return REGISTRY
    @app.get('/v1/objects/{kind}')
    def objects(request:Request,kind:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return list_objects(db,who,kind)
    @app.get('/v1/objects/{kind}/{ident}')
    def object_by_id(request:Request,kind:str,ident:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return object_detail(db,who,kind,ident)
    ai_engine=Engine()
    @app.get('/v1/ai/status')
    def ai_status(request:Request):
        auth.dashboard(request)
        return ai_engine.status()
    @app.get('/v1/incidents/{ident}/ai-summary')
    def ai_summary(request:Request,ident:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: incident=object_detail(db,who,'incident',ident)  # 404 for another tenant's incident
        return ai_engine.explain(incident['properties'])
    @app.get('/v1/lineage/incident/{ident}')
    def incident_evidence(request:Request,ident:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return incident_lineage(db,who,ident)
    @app.get('/v1/lineage/payload/{ident}')
    def payload_evidence(request:Request,ident:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return payload_lineage(db,who,ident)
    @app.get('/v1/actions')
    def actions_list(request:Request,incident_id:str|None=None):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return {'types':TYPES,'actions':list_actions(db,incident_id)}
    @app.get('/v1/actions/{ident}')
    def action_get(request:Request,ident:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return get_action(db,ident)
    @app.post('/v1/actions/propose')
    async def action_propose(request:Request):
        who=auth.dashboard(request); _,data=await body(request)
        with store.connect(who.tenant) as db: return propose(db,who,data)
    @app.post('/v1/actions/{ident}/{operation}')
    def action_transition(request:Request,ident:str,operation:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db: return transition(db,who,ident,operation)
    @app.get('/v1/noise')
    def noise(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:
            rows=[json.loads(r['data']) for r in db.execute('SELECT data FROM incidents')]
            alerts=sum(r.get('alert_count',0) for r in rows); incidents_count=len(rows)
            return {'alerts':alerts,'incidents':incidents_count,'reduction_ratio':round(1-incidents_count/alerts,4) if alerts else None,'scope':'all retained incidents; correlated alerts only'}
    @app.get('/v1/stream')
    async def stream(request:Request):
        who=auth.dashboard(request)
        def snapshot():
            with store.connect(who.tenant) as db:
                refresh(db,config)
                return {'fleet':[{k:v for k,v in r.items() if k!="tenant_id"} for r in db.execute('SELECT * FROM fleet')],'incidents':[json.loads(r['data']) for r in db.execute('SELECT data FROM incidents ORDER BY last_ts DESC LIMIT 100')],'metrics':[json.loads(r['data']) for r in db.execute('SELECT data FROM payloads WHERE metric IS NOT NULL ORDER BY ts DESC LIMIT 100')]}
        async def generate():
            while not await request.is_disconnected():
                async with condition: version=versions.get(who.tenant,0)
                yield 'event: snapshot\ndata: '+dump(await asyncio.to_thread(snapshot))+'\n\n'
                async with condition:
                    try: await asyncio.wait_for(condition.wait_for(lambda: versions.get(who.tenant,0)!=version),timeout=15)
                    except asyncio.TimeoutError: pass
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return app
app=create_app()
