import hashlib,hmac,json,time,os
from fastapi.testclient import TestClient
from saas.main import create_app
from saas.store import utc
import pytest
AUTH={'collectors':{'c1':{'tenant':'t1','region':'in','collector':'one','secret':'secret1'},'c2':{'tenant':'t2','region':'in','collector':'two','secret':'secret2'},'eu':{'tenant':'t3','region':'eu','collector':'three','secret':'secret3'}},'dashboard':{'d1':{'tenant':'t1','region':'in','role':'operator'},'d2':{'tenant':'t2','region':'in','role':'viewer'},'d3':{'tenant':'t3','region':'eu','role':'operator'}}}
@pytest.fixture
def db_url():
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('Set TEST_DATABASE_URL to a dedicated migrated test database')
    from saas.store import Store
    store=Store(url)
    for tenant in ('t1','t2','t3'):
        with store.connect(tenant) as db:
            for table in ('payloads','fleet','health_history','incidents','audit','health_signals','offline_measurements','alert_measurements','renders','counters'):
                db.execute('DELETE FROM '+table)
    return url
@pytest.fixture
def client(db_url):
    with TestClient(create_app('in',db_url,AUTH)) as c: yield c

def p(id='p1',ts=None,val=25,name='cpu',tenant='t1',collector='one',region='in'):
    return {'payload_id':id,'tenant_ref':tenant,'collector_id':collector,'source_id':'host-a','region':region,'event_ts_utc':utc(ts),'source_tz':'Asia/Kolkata','window_s':5,'metric':{'name':name,'value':val,'unit':'%'},'health_state':'Excellent','collector_version':'1.0'}
def post(c,obj,key='c1',path='/v1/ingest',bad=False):
    raw=json.dumps(obj).encode(); sig=hmac.new(AUTH['collectors'][key]['secret'].encode(),raw,hashlib.sha256).hexdigest()
    return c.post(path,content=raw,headers={'X-Collector-Key':key,'X-Signature':'wrong' if bad else sig,'Content-Type':'application/json'})
def get(c,path,key='d1'): return c.get(path,headers={'Authorization':'Bearer '+key})
def test_dedup(client):
    v=p(); assert post(client,v).json()['accepted']==['p1']; assert post(client,v).json()['duplicate']==['p1']; assert len(get(client,'/v1/metrics').json())==1
    assert post(client,{**v,'metric':{**v['metric'],'value':99}}).json()['conflict']==['p1']
def test_isolation(client):
    assert post(client,p()).status_code==200; assert get(client,'/v1/fleet','d2').json()==[]; assert get(client,'/v1/metrics','d2').json()==[]
    assert post(client,p(tenant='t2')).status_code==403; assert post(client,p(),key='c2').status_code==403
    assert get(client,'/v1/fleet','d3').status_code==403
    assert post(client,p(tenant='t3',collector='three',region='eu'),key='eu').status_code==403
    assert post(client,p('p1',tenant='t2',collector='two'),key='c2').json()['accepted']==['p1']
def test_ordering(client):
    now=time.time(); post(client,p('new',now-1)); post(client,p('old',now-10)); assert [x['payload_id'] for x in get(client,'/v1/metrics').json()]==['old','new']
def test_allowlist(client):
    assert post(client,{**p(),'raw_log':'password=secret'}).status_code==422
    assert post(client,p(),bad=True).status_code==401
    v=p(); v.pop('metric'); v['event']={'category':'failed_login','severity':'warning','count':3,'summary':'password=abc'}; assert post(client,v).status_code==422
    assert client.get('/v1/fleet').status_code==401
    assert get(client,'/v1/metrics').json()==[]
def test_anomaly_correlation_and_approval(client):
    now=time.time(); history=[p(f'base{i}',now-30+i,val=20+i%2) for i in range(8)]
    assert len(post(client,history).json()['accepted'])==8
    # Below critical threshold: proves adaptive baseline can flag a noncritical metric.
    assert post(client,p('spike',now-2,val=50)).status_code==200
    event=p('login',now-1);event.pop('metric');event['event']={'category':'failed_login','severity':'warning','count':5,'summary':'Repeated authentication failures'}
    assert post(client,event).status_code==200
    inc=get(client,'/v1/incidents').json(); assert len(inc)==1 and inc[0]['alert_count']==2
    assert inc[0]['signals'][0]['method']=='rolling median/MAD'; assert inc[0]['recommendation']['why']
    path='/v1/remediation/'+inc[0]['id']+'/approve'; assert client.post(path,headers={'Authorization':'Bearer d2'}).status_code==403
    assert client.post(path,headers={'Authorization':'Bearer d1'}).json()['status']=='simulated'
def test_proof(client):
    post(client,p()); assert get(client,'/v1/proof').json()['p95_dashboard_latency_s'] is None
    assert client.post('/v1/proof/render?payload_id=p1',headers={'Authorization':'Bearer d1'}).status_code==200
    r=get(client,'/v1/proof').json(); assert r['received_unique']==1 and r['dashboard_samples']==1 and r['p95_dashboard_latency_s'] is not None
    assert r['lost_count'] is None

def test_offline(db_url):
    import yaml
    from pathlib import Path
    from saas.store import Store
    from saas.ingest import refresh
    config=yaml.safe_load(Path('saas/config/thresholds.yaml').read_text()); now=time.time()
    with TestClient(create_app('in',db_url,AUTH)) as c:
        h={'collector_id':'one','collector_version':'1.0','config_hash':'hash','resource_usage':{'cpu':20.0}}
        assert post(c,h,path='/v1/heartbeat').status_code==200
        with Store(db_url).connect('t1') as db: db.execute('UPDATE fleet SET last_seen=?',(now-61,)); refresh(db,config)
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
    with Store(db_url).connect('t2') as db:
        assert db.execute('SELECT * FROM payloads').fetchall()==[]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.conn.transaction(): db.conn.execute("INSERT INTO signal.counters(tenant_id,name,value) VALUES ('t1','bad',1)")
    with psycopg.connect(db_url) as db: assert db.execute('SELECT count(*) FROM signal.payloads').fetchone()[0]==0
