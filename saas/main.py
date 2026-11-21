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
from .store import Store,utc,epoch,dump,state,audit
from .ingest import process,refresh
from .llm import Engine
from . import rbac, users
from .enroll import TENANT
from .proof import proof
from .contract import validate_contract
from .ontology import REGISTRY, list_objects, object_detail, incident_lineage, payload_lineage
from .actions import TYPES, list_actions, propose, get_action, transition
from .enroll import create_token, enroll

class SecureHeaders:
    """Adds protective headers to every response without buffering or wrapping the body (event streams stay streams)."""
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope['type']!='http': return await self.app(scope, receive, send)
        https=scope.get('scheme')=='https'
        async def send_with_headers(message):
            if message['type']=='http.response.start':
                headers=list(message.get('headers',[])); present={k.lower() for k,_ in headers}
                add=[(b'x-content-type-options',b'nosniff'),(b'x-frame-options',b'DENY'),(b'referrer-policy',b'no-referrer'),
                     (b'content-security-policy',b"default-src 'none'; frame-ancestors 'none'")]
                if https: add.append((b'strict-transport-security',b'max-age=31536000'))
                if scope.get('path','').startswith('/v1/'): add.append((b'cache-control',b'no-store'))
                headers+= [(k,v) for k,v in add if k not in present]
                message={**message,'headers':headers}
            await send(message)
        await self.app(scope, receive, send_with_headers)

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
        who=need(request,'enrollment.create'); _,data=await body(request)
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
        who=need(request,'read')
        with store.connect(who.tenant,lock='try') as db:  # reads never queue behind ingest; only a lock holder may refresh (it writes)
            if db.locked: refresh(db,config)
            return [{**{k:v for k,v in r.items() if k!="tenant_id"},'collector_id':r['id'],'last_seen_utc':utc(r['last_seen']),'resources':json.loads(r['resources']),'online':time.time()-r['last_seen']<config['offline_after_s']} for r in db.execute('SELECT * FROM fleet ORDER BY id')]
    @app.get('/v1/session')
    def session(request:Request):
        who=auth.dashboard(request)
        return {'tenant_id':who.tenant,'region':who.region,'role':who.role,'permissions':rbac.permissions_of(who.role) if not who.must_change else [],
                'user':who.user,'display_name':who.display_name,'must_change_password':who.must_change,'auth':'session' if who.user else 'api-token'}
    # ---- sign-in, sessions and user management ----
    def clean_user_fields(data,creating):
        if not isinstance(data,dict): raise HTTPException(422,'Expected a JSON object')
        allowed={'username','display_name','role','temporary_password'} if creating else {'display_name','role','active'}
        if set(data)-allowed: raise HTTPException(422,'Unknown field(s): '+', '.join(sorted(set(data)-allowed)))
        out={}
        if 'role' in data:
            if data['role'] not in rbac.ROLES: raise HTTPException(422,'Role must be one of: '+', '.join(rbac.ROLES))
            out['role']=data['role']
        if 'display_name' in data:
            name=data['display_name']
            if not isinstance(name,str) or not 1<=len(name.strip())<=80: raise HTTPException(422,'Display name must be 1 to 80 characters')
            out['display_name']=name.strip()
        if 'active' in data:
            if not isinstance(data['active'],bool): raise HTTPException(422,'active must be true or false')
            out['active']=data['active']
        return out
    @app.post('/v1/login')
    async def login(request:Request):
        if not auth.session_secret: raise HTTPException(503,'Sign-in is not configured on this platform')
        _,data=await body(request)
        data=data if isinstance(data,dict) else {}
        tenant,username,password=data.get('tenant'),data.get('username'),data.get('password')
        bad=HTTPException(401,'Invalid organization, username or password')
        if not (isinstance(tenant,str) and TENANT.fullmatch(tenant.strip()) and isinstance(username,str) and isinstance(password,str) and 0<len(password)<=256): raise bad
        tenant,username=tenant.strip(),username.strip().lower()
        def work():
            with store.connect(tenant,lock=False) as db: return users.authenticate(db,username,password)
        user,reason=await asyncio.to_thread(work)
        if reason=='locked': raise HTTPException(429,'Too many failed attempts. Try again in a few minutes, or ask an administrator to reset your password.')
        if not user: raise bad
        token,exp=users.issue_token(auth.session_secret,tenant,username,user['token_version'])
        return {'token':token,'expires_at':exp,'user':users.public(user),'tenant_id':tenant,'region':region}
    @app.post('/v1/logout')
    def logout(request:Request):
        who=auth.dashboard(request)
        if who.user:
            with store.connect(who.tenant,lock=False) as db:
                db.execute('UPDATE users SET token_version=token_version+1 WHERE username=?',(who.user,)); audit(db,'logout',who.user,{'actor':who.user})
        return {'signed_out':True}
    @app.post('/v1/me/password')
    async def change_own_password(request:Request):
        who=auth.dashboard(request)
        if not who.user: raise HTTPException(403,'API tokens have no password')
        _,data=await body(request)
        if not isinstance(data,dict) or set(data)-{'current_password','new_password'}: raise HTTPException(422,'Expected current_password and new_password')
        problem=users.password_problem(data.get('new_password'),who.user)
        if problem: raise HTTPException(422,problem)
        def work():
            with store.connect(who.tenant,lock=False) as db:
                row,reason=users.authenticate(db,who.user,str(data.get('current_password','')))
                if not row: return None,reason
                users.set_password(db,who.user,who.user,data['new_password'],False,'password_changed')
                return users.get_user(db,who.user),'ok'
        row,reason=await asyncio.to_thread(work)
        if reason=='locked': raise HTTPException(429,'Too many failed attempts. Try again in a few minutes.')
        if not row: raise HTTPException(403,'The current password is not correct')
        token,exp=users.issue_token(auth.session_secret,who.tenant,who.user,row['token_version'])
        return {'token':token,'expires_at':exp,'user':users.public(row)}
    @app.get('/v1/users')
    def list_all_users(request:Request):
        who=need(request,'users.manage')
        with store.connect(who.tenant,lock=False) as db: return users.list_users(db)
    @app.post('/v1/users')
    async def create_new_user(request:Request):
        who=need(request,'users.manage'); _,data=await body(request)
        fields=clean_user_fields(data,True)
        username=str(data.get('username','')).strip().lower()
        if not users.USERNAME.fullmatch(username): raise HTTPException(422,'Username: 2 to 40 characters, lower-case letters, digits, dot, dash or underscore')
        if not fields.get('display_name') or 'role' not in fields: raise HTTPException(422,'display_name and role are required')
        problem=users.password_problem(data.get('temporary_password'),username)
        if problem: raise HTTPException(422,problem)
        with store.connect(who.tenant) as db:
            if users.get_user(db,username): raise HTTPException(409,'That username is already taken')
            return users.create_user(db,who.user or 'api-token',username,fields['display_name'],fields['role'],data['temporary_password'])
    @app.patch('/v1/users/{username}')
    async def change_user(request:Request,username:str):
        who=need(request,'users.manage'); _,data=await body(request)
        changes=clean_user_fields(data,False)
        if not changes: raise HTTPException(422,'Nothing to change: send role, active or display_name')
        with store.connect(who.tenant) as db:
            target=users.get_user(db,username)
            if not target: raise HTTPException(404,'No such user')
            losing_admin=target['role']=='admin' and target['active'] and (changes.get('role',target['role'])!='admin' or changes.get('active',True) is False)
            if losing_admin and users.active_admins_except(db,username)==0: raise HTTPException(409,'This is the last active administrator. Make another user an administrator first.')
            if username==who.user and changes.get('active') is False: raise HTTPException(409,'You cannot disable your own account.')
            return users.update_user(db,who.user or 'api-token',username,changes)
    @app.post('/v1/users/{username}/password')
    async def reset_user_password(request:Request,username:str):
        who=need(request,'users.manage'); _,data=await body(request)
        if not isinstance(data,dict) or set(data)-{'temporary_password'}: raise HTTPException(422,'Expected temporary_password')
        problem=users.password_problem(data.get('temporary_password'),username)
        if problem: raise HTTPException(422,problem)
        with store.connect(who.tenant) as db:
            if not users.get_user(db,username): raise HTTPException(404,'No such user')
            users.set_password(db,who.user or 'api-token',username,data['temporary_password'],True,'password_reset')
            return users.public(users.get_user(db,username))
    @app.get('/v1/audit')
    def audit_log(request:Request,limit:int=100):
        who=need(request,'audit.read')
        with store.connect(who.tenant,lock=False) as db:
            rows=db.execute('SELECT action,reference,ts,detail FROM audit ORDER BY ts DESC LIMIT ?',(max(1,min(limit,500)),)).fetchall()
        return [{'action':r['action'],'reference':r['reference'],'ts':r['ts'],'detail':json.loads(r['detail'])} for r in rows]
    @app.get('/v1/rbac')
    def rbac_matrix(request:Request):
        who=need(request,'read')
        return {**rbac.matrix(),'you':{'role':who.role,'permissions':rbac.permissions_of(who.role)}}
    @app.get('/v1/health/thresholds')
    def health_thresholds(request:Request):
        need(request,'read')
        return {k:config[k] for k in ('metrics','stale_after_s','offline_after_s','baseline_min','baseline_window','anomaly_persistence_windows') if k in config}
    @app.get('/v1/system/status')
    def system_status(request:Request):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db:
            collectors=db.execute('SELECT COUNT(*) AS n FROM fleet').fetchone()['n']
            payloads=db.execute('SELECT COUNT(*) AS n FROM payloads').fetchone()['n']
            incidents=db.execute('SELECT COUNT(*) AS n FROM incidents').fetchone()['n']
        return {'tenant_id':who.tenant,'region':region,'replica_id':replica_id,'database':'reachable','collectors':collectors,'payloads':payloads,'incidents':incidents}
    @app.get('/v1/metrics')
    def metrics(request:Request,source:str|None=None,name:str|None=None,limit:int=1000):
        who=need(request,'read'); q='SELECT data,received FROM payloads WHERE metric IS NOT NULL'; args=[]
        from .aiops import canonical
        for field,val in [('source',source),('metric',canonical(name) if name else None)]:
            if val is not None: q+=f' AND {field}=?'; args.append(val)
        for key,op in [('from','>='),('to','<=')]:
            if key in request.query_params:
                try: val=utc(epoch(request.query_params[key]))
                except ValueError: raise HTTPException(422,'Invalid timestamp')
                q+=f' AND ts{op}?'; args.append(val)
        with store.connect(who.tenant,lock=False) as db: return [{**json.loads(r['data']),'received_ts_utc':utc(r['received'])} for r in db.execute(q+' ORDER BY ts,id LIMIT ?',(*args,max(1,min(limit,10000))))]
    @app.get('/v1/incidents')
    def incidents(request:Request):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return [json.loads(r['data']) for r in db.execute('SELECT data FROM incidents ORDER BY last_ts DESC')]
    @app.get('/v1/health/history')
    def history(request:Request):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return [{k:v for k,v in r.items() if k!="tenant_id"} for r in db.execute('SELECT * FROM health_history ORDER BY id DESC LIMIT 1000')]
    @app.get('/v1/proof')
    def evidence(request:Request,window_s:int|None=None):
        who=need(request,'read')
        if window_s is not None and not 60<=window_s<=86400: raise HTTPException(422,'window_s must be between 60 and 86400')
        with store.connect(who.tenant,lock=False) as db:return proof(db,window_s)
    @app.post('/v1/proof/render')
    def render(request:Request,payload_id:str):
        who=need(request,'read')
        with store.connect(who.tenant) as db:
            if not db.execute('SELECT id FROM payloads WHERE id=?',(payload_id,)).fetchone(): raise HTTPException(404,'Unknown payload')
            db.execute('INSERT INTO renders(id,rendered) VALUES(?,?) ON CONFLICT(tenant_id,id) DO NOTHING',(payload_id,time.time()))
        return {'acknowledged':True}
    @app.post('/v1/remediation/{id}/approve')
    def remediation(request:Request,id:str):
        need(request,'action.decide')
        raise HTTPException(410,'Use the simulated action proposal and approval lifecycle')
    @app.get('/v1/ontology')
    def ontology(request:Request):
        need(request,'read')
        return REGISTRY
    @app.get('/v1/objects/{kind}')
    def objects(request:Request,kind:str):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return list_objects(db,who,kind)
    @app.get('/v1/objects/{kind}/{ident}')
    def object_by_id(request:Request,kind:str,ident:str):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return object_detail(db,who,kind,ident)
    ai_engine=Engine()
    rbac.validate_config(auth.config)
    def need(request,permission):
        who=auth.dashboard(request)
        if who.must_change: raise HTTPException(403,'Change your temporary password before continuing.')
        if not rbac.can(who.role,permission):
            try:
                with store.connect(who.tenant) as db: audit(db,'access_denied',request.url.path,{'role':who.role,'actor':who.user or 'api-token','permission':permission,'method':request.method})
            except Exception: logging.exception('Could not audit a denied request')
            raise HTTPException(403,f"The {who.role} role cannot {permission}. {rbac.PERMISSIONS.get(permission,'')}")
        return who
    @app.get('/v1/ai/status')
    def ai_status(request:Request):
        need(request,'read')
        return ai_engine.status()
    @app.get('/v1/incidents/{ident}/ai-summary')
    def ai_summary(request:Request,ident:str):
        who=need(request,'ai.summary')
        with store.connect(who.tenant,lock=False) as db: incident=object_detail(db,who,'incident',ident)  # 404 for another tenant's incident
        return ai_engine.explain(incident['properties'])
    @app.get('/v1/lineage/incident/{ident}')
    def incident_evidence(request:Request,ident:str):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return incident_lineage(db,who,ident)
    @app.get('/v1/lineage/payload/{ident}')
    def payload_evidence(request:Request,ident:str):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return payload_lineage(db,who,ident)
    @app.get('/v1/actions')
    def actions_list(request:Request,incident_id:str|None=None):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return {'types':TYPES,'actions':list_actions(db,incident_id)}
    @app.get('/v1/actions/{ident}')
    def action_get(request:Request,ident:str):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db: return get_action(db,ident)
    @app.post('/v1/actions/propose')
    async def action_propose(request:Request):
        who=need(request,'action.propose'); _,data=await body(request)
        with store.connect(who.tenant) as db: return propose(db,who,data)
    @app.post('/v1/actions/{ident}/{operation}')
    def action_transition(request:Request,ident:str,operation:str):
        who=need(request,'action.decide')
        with store.connect(who.tenant) as db: return transition(db,who,ident,operation)
    @app.get('/v1/noise')
    def noise(request:Request):
        who=need(request,'read')
        with store.connect(who.tenant,lock=False) as db:
            rows=[json.loads(r['data']) for r in db.execute('SELECT data FROM incidents')]
            alerts=sum(r.get('alert_count',0) for r in rows); incidents_count=len(rows)
            return {'alerts':alerts,'incidents':incidents_count,'reduction_ratio':round(1-incidents_count/alerts,4) if alerts else None,'scope':'all retained incidents; correlated alerts only'}
    @app.get('/v1/stream')
    async def stream(request:Request):
        who=need(request,'read')
        def snapshot():
            with store.connect(who.tenant,lock='try') as db:
                if db.locked: refresh(db,config)
                return {'fleet':[{k:v for k,v in r.items() if k!="tenant_id"} for r in db.execute('SELECT * FROM fleet')],'incidents':[json.loads(r['data']) for r in db.execute('SELECT data FROM incidents ORDER BY last_ts DESC LIMIT 100')],'metrics':[json.loads(r['data']) for r in db.execute('SELECT data FROM payloads WHERE metric IS NOT NULL ORDER BY ts DESC LIMIT 100')]}
        async def generate():
            while not await request.is_disconnected():
                async with condition: version=versions.get(who.tenant,0)
                yield 'event: snapshot\ndata: '+dump(await asyncio.to_thread(snapshot))+'\n\n'
                async with condition:
                    try: await asyncio.wait_for(condition.wait_for(lambda: versions.get(who.tenant,0)!=version),timeout=15)
                    except asyncio.TimeoutError: pass
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return SecureHeaders(app)
app=create_app()
