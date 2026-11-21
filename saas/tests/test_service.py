import hashlib,hmac,json,time,os,uuid
from fastapi.testclient import TestClient
from saas.main import create_app
from saas.store import utc
import pytest
AUTH={'collectors':{'c1':{'tenant':'t-one','region':'in','collector':'col-one','secret':'secret1'},'c2':{'tenant':'t-two','region':'in','collector':'col-two','secret':'secret2'},'eu':{'tenant':'t-three','region':'eu','collector':'col-three','secret':'secret3'}},'dashboard':{'admin':{'tenant':'t-one','region':'in','role':'admin'},'dv':{'tenant':'t-one','region':'in','role':'viewer'},'dau':{'tenant':'t-one','region':'in','role':'auditor'},'d1':{'tenant':'t-one','region':'in','role':'operator'},'d2':{'tenant':'t-two','region':'in','role':'viewer'},'d3':{'tenant':'t-three','region':'eu','role':'operator'}}}
@pytest.fixture
def db_url():
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('Set TEST_DATABASE_URL to a dedicated migrated test database')
    from saas.store import Store
    store=Store(url)
    for tenant in ('t-one','t-two','t-three'):
        with store.connect(tenant) as db:
            for table in ('enrollment_tokens','collector_credentials','actions','anomaly_pending','payloads','fleet','health_history','incidents','audit','health_signals','offline_measurements','alert_measurements','renders','counters'):
                db.execute('DELETE FROM '+table)
    return url
@pytest.fixture
def client(db_url):
    with TestClient(create_app('in',db_url,AUTH)) as c: yield c

def pid(label): return str(uuid.uuid5(uuid.NAMESPACE_DNS,label))
def p(id='p1',ts=None,val=25,name='cpu',tenant='t-one',collector='col-one',region='in'):
    name={'cpu':'cpu_pct','memory':'mem_pct'}.get(name,name)
    return {'payload_id':pid(id),'tenant_ref':tenant,'collector_id':collector,'source_id':'src_12345678','region':region,'event_ts_utc':utc(ts),'source_tz':'Asia/Kolkata','window_s':5,'metric':{'name':name,'value':val,'unit':'%'},'health_state':'Excellent','collector_version':'1.0.0'}
def post(c,obj,key='c1',path='/v1/ingest',bad=False):
    raw=json.dumps(obj).encode(); sig=hmac.new(AUTH['collectors'][key]['secret'].encode(),raw,hashlib.sha256).hexdigest()
    return c.post(path,content=raw,headers={'X-Collector-Key':key,'X-Signature':'wrong' if bad else sig,'Content-Type':'application/json'})
def get(c,path,key='d1'): return c.get(path,headers={'Authorization':'Bearer '+key})
def test_dedup(client):
    v=p(); assert post(client,v).json()['accepted']==[pid('p1')]; assert post(client,v).json()['duplicate']==[pid('p1')]; assert len(get(client,'/v1/metrics').json())==1
    assert post(client,{**v,'metric':{**v['metric'],'value':99}}).json()['conflict']==[pid('p1')]
def test_isolation(client):
    assert post(client,p()).status_code==200; assert get(client,'/v1/fleet','d2').json()==[]; assert get(client,'/v1/metrics','d2').json()==[]
    assert post(client,p(tenant='t-two')).status_code==403; assert post(client,p(),key='c2').status_code==403
    assert get(client,'/v1/fleet','d3').status_code==403
    assert post(client,p(tenant='t-three',collector='col-three',region='eu'),key='eu').status_code==403
    assert post(client,p('p1',tenant='t-two',collector='col-two'),key='c2').json()['accepted']==[pid('p1')]
def test_ordering(client):
    now=time.time(); post(client,p('new',now-1)); post(client,p('old',now-10)); assert [x['payload_id'] for x in get(client,'/v1/metrics').json()]==[pid('old'),pid('new')]
def test_allowlist(client):
    assert post(client,{**p(),'raw_log':'password=secret'}).status_code==422
    assert post(client,p(),bad=True).status_code==401
    v=p(); v.pop('metric'); v['event']={'category':'auth_failure_burst','severity':'warning','count':3,'summary':'password=abc'}; assert post(client,v).status_code==422
    assert client.get('/v1/fleet').status_code==401
    assert get(client,'/v1/metrics').json()==[]
def test_anomaly_correlation_and_approval(client):
    now=time.time(); history=[p(f'base{i}',now-30+i,val=20+i%2) for i in range(8)]
    assert len(post(client,history).json()['accepted'])==8
    # Below critical threshold: proves adaptive baseline can flag a noncritical metric.
    assert post(client,p('spike1',now-3,val=50)).status_code==200
    assert get(client,'/v1/incidents').json()==[]
    assert post(client,p('spike2',now-2,val=50)).status_code==200
    event=p('login',now-1);event.pop('metric');event['event']={'category':'auth_failure_burst','severity':'warning','count':5,'summary':'Repeated authentication failures'}
    assert post(client,event).status_code==200
    inc=get(client,'/v1/incidents').json(); assert len(inc)==1 and inc[0]['alert_count']==2
    assert inc[0]['signals'][0]['method']=='rolling median/MAD'; assert inc[0]['recommendation']['why']
    path='/v1/remediation/'+inc[0]['id']+'/approve'; assert client.post(path,headers={'Authorization':'Bearer d1'}).status_code==410
def test_proof(client):
    post(client,p()); assert get(client,'/v1/proof').json()['p95_dashboard_latency_s'] is None
    assert client.post('/v1/proof/render?payload_id='+pid('p1'),headers={'Authorization':'Bearer d1'}).status_code==200
    r=get(client,'/v1/proof').json(); assert r['received_unique']==1 and r['dashboard_samples']==1 and r['p95_dashboard_latency_s'] is not None
    assert r['lost_count'] is None

def test_offline(db_url):
    import yaml
    from pathlib import Path
    from saas.store import Store
    from saas.ingest import refresh
    config=yaml.safe_load(Path('saas/config/thresholds.yaml').read_text()); now=time.time()
    with TestClient(create_app('in',db_url,AUTH)) as c:
        h={'collector_id':'col-one','collector_version':'1.0.0','config_hash':'hash','resource_usage':{'cpu':20.0}}
        assert post(c,h,path='/v1/heartbeat').status_code==200
        with Store(db_url).connect('t-one') as db: db.execute('UPDATE fleet SET last_seen=?',(now-61,)); refresh(db,config)
        assert get(c,'/v1/fleet').json()[0]['state']=='Poor'
        assert post(c,h,path='/v1/heartbeat').status_code==200
        assert get(c,'/v1/fleet').json()[0]['state']=='Good'
def test_health_aggregation(client):
    now=time.time(); post(client,p('critical',now-2,val=99)); post(client,p('normal',now-1,val=30,name='memory'))
    assert get(client,'/v1/fleet').json()[0]['state']=='Poor'
    post(client,p('recovery',now,val=25)); assert get(client,'/v1/fleet').json()[0]['state']=='Excellent'


def test_two_replicas_concurrent_dedup(db_url):
    from concurrent.futures import ThreadPoolExecutor
    v=p('shared')
    with TestClient(create_app('in',db_url,AUTH,replica_id='1')) as a, TestClient(create_app('in',db_url,AUTH,replica_id='2')) as b:
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda c:post(c,v).json(),[a,b]))
        assert sum(len(r['accepted']) for r in results)==1
        assert sum(len(r['duplicate']) for r in results)==1
        assert len(get(b,'/v1/metrics').json())==1
    with TestClient(create_app('in',db_url,AUTH,replica_id='2')) as survivor:
        assert get(survivor,'/v1/proof').json()['received_unique']==1

def test_rls_direct(db_url):
    import psycopg
    from saas.store import Store
    with TestClient(create_app('in',db_url,AUTH)) as c: assert post(c,p()).status_code==200
    with Store(db_url).connect('t-two') as db:
        assert db.execute('SELECT * FROM payloads').fetchall()==[]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.conn.transaction(): db.conn.execute("INSERT INTO signal.counters(tenant_id,name,value) VALUES ('t-one','bad',1)")
    with psycopg.connect(db_url) as db: assert db.execute('SELECT count(*) FROM signal.payloads').fetchone()[0]==0


def test_contract_rejects_forbidden_fields_and_values(client):
    good = p('contract')
    for change in (
        {'source_id':'10.2.4.5'},
        {'payload_id':'not-a-uuid'},
        {'window_s':0},
        {'collector_version':'1.0'},
        {'metric':{'name':'made_up_metric','value':1,'unit':'%'}},
        {'raw_log':'secret'},
    ):
        assert post(client, {**good, **change}).status_code == 422
    assert post(client, good).status_code == 200


def test_ontology_lineage_actions_and_role_isolation(client):
    event = p('security')
    event.pop('metric')
    event['event'] = {'category':'auth_failure_burst','severity':'high','count':42,'summary':'repeated failed logins'}
    assert post(client,event).status_code == 200
    incident = get(client,'/v1/incidents').json()[0]
    ident = incident['id']
    assert get(client,'/v1/ontology').json()['types']['source']['properties']['id'] == 'PSEUDONYMIZED'
    obj = get(client,f'/v1/objects/incident/{ident}').json()
    assert obj['links']['collector'] == 'col-one'
    assert obj['links']['source'] == 'src_12345678'
    assert obj['links']['observations'] == [pid('security')]
    assert get(client,f'/v1/lineage/incident/{ident}').json()['payload_ids'] == [pid('security')]
    assert get(client,f'/v1/lineage/payload/{pid("security")}').json()['incidents'][0]['incident_id'] == ident
    assert get(client,f'/v1/objects/incident/{ident}','d2').status_code == 404
    assert get(client,f'/v1/lineage/payload/{pid("security")}','d2').status_code == 404
    assert get(client,'/v1/noise').json()['alerts'] == 1
    payload = {'incident_id':ident,'action_type':'restart_service','parameters':{'service':'api-service'}}
    headers = {'Authorization':'Bearer d1'}
    assert client.post('/v1/actions/propose',json=payload,headers={'Authorization':'Bearer dv'}).status_code == 403
    assert client.post('/v1/actions/propose',json={**payload,'parameters':{'service':'api;reboot'}},headers=headers).status_code == 422
    assert client.post('/v1/actions/propose',json={**payload,'action_type':'isolate_source','parameters':{'source_id':'src_87654321'}},headers=headers).status_code == 422
    response = client.post('/v1/actions/propose',json=payload,headers=headers)
    assert response.status_code == 200
    action = response.json(); action_id = action['id']
    assert action['status'] == 'proposed' and action['simulation_only'] is True
    assert get(client,f'/v1/actions/{action_id}','d2').status_code == 404
    assert client.post(f'/v1/actions/{action_id}/approve',headers={'Authorization':'Bearer dv'}).status_code == 403
    assert client.post(f'/v1/actions/{action_id}/rollback',headers=headers).status_code == 409
    approved=client.post(f'/v1/actions/{action_id}/approve',headers=headers)
    assert approved.json()['status'] == 'approved'
    assert client.post(f'/v1/actions/{action_id}/approve',headers=headers).status_code == 409
    rolled=client.post(f'/v1/actions/{action_id}/rollback',headers=headers).json()
    assert rolled['status'] == 'rolled_back'
    assert [entry['action'] for entry in rolled['audit']] == ['action_proposed','action_approved','action_rolled_back']
    assert action_id in get(client,f'/v1/objects/incident/{ident}').json()['links']['actions']
    assert get(client,'/v1/actions','d2').json()['actions'] == []


def test_baseline_requires_persistence_and_ignores_late_windows(client):
    now=time.time()
    assert len(post(client,[p(f'normal{i}',now-40+i,val=20+i%2) for i in range(8)]).json()['accepted'])==8
    assert post(client,p('one-spike',now-10,val=50)).status_code == 200
    assert get(client,'/v1/incidents').json() == []
    assert post(client,p('late-normal',now-20,val=20)).status_code == 200
    assert post(client,p('second-spike',now-9,val=50)).status_code == 200
    result=get(client,'/v1/incidents').json()
    assert len(result)==1
    assert result[0]['signals'][0]['persistence_windows']==2
    assert post(client,p('third-spike',now-8,val=50)).status_code == 200
    assert get(client,'/v1/incidents').json()[0]['alert_count'] == 1


def test_one_time_enrollment_and_enrolled_hmac(client):
    request_body={'collector_id':'col-new','expires_in_s':60}
    assert client.post('/v1/enrollment-tokens',json=request_body,headers={'Authorization':'Bearer d1'}).status_code==403
    created=client.post('/v1/enrollment-tokens',json=request_body,headers={'Authorization':'Bearer admin'})
    assert created.status_code==200 and created.headers['cache-control']=='no-store'
    token=created.json()['token']
    assert client.post('/v1/enroll',json={'tenant_ref':'t-two','token':token}).status_code==401
    accepted=client.post('/v1/enroll',json={'tenant_ref':'t-one','token':token})
    assert accepted.status_code==200 and accepted.headers['cache-control']=='no-store'
    credential=accepted.json()
    assert client.post('/v1/enroll',json={'tenant_ref':'t-one','token':token}).status_code==401
    payload=p('enrolled',collector='col-new')
    raw=json.dumps(payload).encode()
    sig=hmac.new(credential['collector_secret'].encode(),raw,hashlib.sha256).hexdigest()
    headers={'X-Collector-Key':credential['collector_key'],'X-Signature':sig,'Content-Type':'application/json'}
    assert client.post('/v1/ingest',content=raw,headers=headers).json()['accepted']==[pid('enrolled')]
    assert client.post('/v1/ingest',content=raw+b' ',headers=headers).status_code==401
    assert get(client,'/v1/fleet','d2').json()==[]
    from saas.store import Store
    with Store(os.environ['TEST_DATABASE_URL']).connect('t-one') as db:
        row=db.execute('SELECT key_hash,signing_secret FROM collector_credentials').fetchone()
        assert credential['collector_key'] not in row['key_hash']


def test_separate_regions_require_separate_bound_databases(db_url):
    eu_url=os.getenv('TEST_DATABASE_URL_EU')
    if not eu_url: pytest.skip('Set TEST_DATABASE_URL_EU to a second dedicated migrated database')
    from saas.store import Store
    with Store(eu_url).connect('t-three') as db:
        for table in ('enrollment_tokens','collector_credentials','actions','anomaly_pending','payloads','fleet','health_history','incidents','audit','health_signals','offline_measurements','alert_measurements','renders','counters'):
            db.execute('DELETE FROM '+table)
    with TestClient(create_app('in',db_url,AUTH)) as india, TestClient(create_app('eu',eu_url,AUTH)) as europe:
        event=p('europe',tenant='t-three',collector='col-three',region='eu')
        assert post(india,event,key='eu').status_code==403
        assert post(europe,event,key='eu').json()['accepted']==[pid('europe')]
        assert get(india,'/v1/fleet','d3').status_code==403
        assert len(get(europe,'/v1/fleet','d3').json())==1
        assert get(india,'/v1/metrics','d1').json()==[]
    with pytest.raises(RuntimeError,match='different region'):
        with TestClient(create_app('eu',db_url,AUTH)): pass


def test_proof_window_filters_old_receipts(client):
    from saas.store import Store
    now=time.time()
    assert post(client,p('old-receipt',now-600)).status_code==200
    assert post(client,p('recent-receipt',now-2)).status_code==200
    with Store(os.environ['TEST_DATABASE_URL']).connect('t-one') as db:
        db.execute('UPDATE payloads SET received=? WHERE id=?',(now-600,pid('old-receipt')))
    window=get(client,'/v1/proof?window_s=300').json()
    assert window['received_ids']==[pid('recent-receipt')]
    assert window['window_s']==300 and window['window_start_utc']
    assert get(client,'/v1/proof?window_s=10').status_code==422
    assert set(get(client,'/v1/proof').json()['received_ids'])=={pid('old-receipt'),pid('recent-receipt')}


def test_edge_aggregation_to_saas_incident_and_lineage(client):
    from collector.config import Config
    from collector.outbox import LocalStore
    from collector.pipeline import Pipeline
    local=LocalStore(':memory:')
    pipeline=Pipeline(Config(data_dir=':memory:',tenant_ref='t-one',collector_id='col-one',region='in',burst_threshold=5),local)
    for _ in range(6):
        pipeline.process('Nov 20 09:16:01 web-1 sshd[88]: Failed password for root from 203.0.113.1')
    pipeline.flush(force=True)
    outgoing=local.pending(50)
    assert len(outgoing)==1 and outgoing[0]['event']['count']==6
    assert '203.0.113.1' not in json.dumps(outgoing) and 'root' not in json.dumps(outgoing)
    assert post(client,outgoing).json()['accepted']==[outgoing[0]['payload_id']]
    incident=get(client,'/v1/incidents').json()[0]
    assert incident['signals'][0]['signal']=='failed_login'
    assert get(client,f"/v1/lineage/incident/{incident['id']}").json()['payload_ids']==[outgoing[0]['payload_id']]


def test_platform_visibility_and_health_reason(client):
    assert client.get('/v1/system/status').status_code == 401
    session = get(client, '/v1/session').json()
    assert {k: session[k] for k in ('tenant_id', 'region', 'role')} == {'tenant_id':'t-one','region':'in','role':'operator'}
    assert 'action.propose' in session['permissions'] and 'enrollment.create' not in session['permissions']
    assert post(client,p('visible',val=99)).status_code == 200
    status=get(client,'/v1/system/status').json()
    assert (status['collectors'],status['payloads'],status['database']) == (1,1,'reachable')
    assert get(client,'/v1/system/status','d2').json()['payloads'] == 0
    assert get(client,'/v1/health/thresholds').json()['metrics']['cpu']['poor'] == 95
    reason=get(client,'/v1/fleet').json()[0]['reason']
    assert 'cpu' in reason and '99' in reason and '95' in reason


def test_phase4_incident_evidence_and_payload_tenant_isolation(client):
    now=time.time()
    normal=[p(f'phase4-normal-{i}',now-25+i,val=20+i%2) for i in range(8)]
    assert len(post(client,normal).json()['accepted'])==8
    assert get(client,'/v1/incidents').json()==[]
    anomaly=p('phase4-critical',now-1,val=99)
    assert post(client,anomaly).status_code==200
    incident=get(client,'/v1/incidents').json()[0]
    signal=incident['signals'][0]
    assert signal['value']==99 and signal['threshold']==95 and signal['comparison']=='>='
    assert signal['event_ts_utc']==anomaly['event_ts_utc'] and signal['alert_ts_utc']
    assert signal['payload_id']==anomaly['payload_id'] and incident['recommendation']['action']
    path='/v1/objects/observation/'+anomaly['payload_id']
    assert get(client,path).json()['properties']['payload_id']==anomaly['payload_id']
    assert get(client,path,'d2').status_code==404


def test_phase4_heartbeat_threshold_from_config(db_url):
    from saas.store import Store
    from saas.ingest import refresh
    from pathlib import Path
    import yaml
    config=yaml.safe_load(Path('saas/config/thresholds.yaml').read_text())
    assert config['offline_after_s']==40
    now=time.time()
    with TestClient(create_app('in',db_url,AUTH)) as c:
        h={'collector_id':'col-one','collector_version':'1.0.0','config_hash':'hash','resource_usage':{'cpu':20.0}}
        assert post(c,h,path='/v1/heartbeat').status_code==200
        with Store(db_url).connect('t-one') as db:
            db.execute('UPDATE fleet SET last_seen=?',(now-41,)); refresh(db,config,now)
            assert db.execute('SELECT state FROM fleet').fetchone()['state']=='Poor'


def test_aiops_lab_auth_isolation_and_read_only_simulation(client):
    now=time.time()
    history=[p(f'forecast-{i}',now-105+i*15,val=40+i*2) for i in range(8)]
    assert len(post(client,history).json()['accepted']) == 8
    path='/v1/forecast?collector=col-one&source=src_12345678&name=cpu_pct&horizon_s=60'
    assert client.get(path).status_code == 401
    predicted=get(client,path).json()
    assert predicted['available'] and predicted['sample_count']==8 and predicted['projected']==62
    assert not get(client,path,'d2').json()['available']
    before=get(client,'/v1/incidents').json()
    simulated=get(client,'/v1/what-if?name=cpu_pct&value=99').json()
    assert simulated['state']=='Poor' and simulated['simulation_only'] is True
    assert get(client,'/v1/incidents').json()==before
    assert get(client,'/v1/what-if?name=cpu_pct&value=101').status_code==422


def test_stream_mode_rejects_unknown_values_before_opening(client):
    assert get(client,'/v1/stream?mode=unknown').status_code == 422
    assert client.get('/v1/stream?mode=changes').status_code == 401
