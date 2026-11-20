import asyncio, json, os, time, logging, gzip, io
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
import yaml
from .schema import Payload,Heartbeat
from .auth import Auth
from .store import Store,utc,epoch,dump,state
from .ingest import process,refresh
from .proof import proof
from .remediation import approve

def create_app(region=None,database_url=None,auth_config=None,thresholds=None,replica_id=None):
    region=region or os.getenv('REGION','in'); store=Store(database_url); auth=Auth(region,auth_config); replica_id=replica_id or os.getenv('REPLICA_ID','1')
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
    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.check)
        task=asyncio.create_task(watchdog())
        try: yield
        finally:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
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
    @app.post('/v1/ingest')
    async def ingest(request:Request):
        raw,obj=await body(request); who=auth.collector(request,raw); items=obj if isinstance(obj,list) else [obj]
        if not 1<=len(items)<=500: raise HTTPException(422,'Batch must contain 1–500 payloads')
        payloads=[validate(Payload,item) for item in items]
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
    def evidence(request:Request):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:return proof(db)
    @app.post('/v1/proof/render')
    def render(request:Request,payload_id:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:
            if not db.execute('SELECT id FROM payloads WHERE id=?',(payload_id,)).fetchone(): raise HTTPException(404,'Unknown payload')
            db.execute('INSERT INTO renders(id,rendered) VALUES(?,?) ON CONFLICT(tenant_id,id) DO NOTHING',(payload_id,time.time()))
        return {'acknowledged':True}
    @app.post('/v1/remediation/{id}/approve')
    def remediation(request:Request,id:str):
        who=auth.dashboard(request)
        with store.connect(who.tenant) as db:return approve(db,id,who)
    @app.get('/v1/stream')
    async def stream(request:Request):
        who=auth.dashboard(request)
        def snapshot():
            with store.connect(who.tenant) as db:
                refresh(db,config)
                return {'fleet':[{k:v for k,v in r.items() if k!="tenant_id"} for r in db.execute('SELECT * FROM fleet')],'incidents':[json.loads(r['data']) for r in db.execute('SELECT data FROM incidents ORDER BY last_ts DESC LIMIT 100')],'metrics':[json.loads(r['data']) for r in db.execute('SELECT data FROM payloads WHERE metric IS NOT NULL ORDER BY ts DESC LIMIT 100')]}
        async def generate():
            while not await request.is_disconnected():
                yield 'event: snapshot\ndata: '+dump(await asyncio.to_thread(snapshot))+'\n\n'; await asyncio.sleep(2)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return app
app=create_app()
