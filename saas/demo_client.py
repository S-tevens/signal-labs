"""Send a deterministic signed payload to both replicas to demonstrate idempotency."""
import argparse, hashlib, hmac, json, os, urllib.request

def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:8000');p.add_argument('--id',default='failover-demo-001');p.add_argument('--ts',required=False,default='2026-01-01T00:00:00Z');a=p.parse_args()
    payload={'payload_id':a.id,'tenant_ref':'t1','collector_id':'one','source_id':'src_demo','region':'in','event_ts_utc':a.ts,'source_tz':'Asia/Kolkata','window_s':5,'metric':{'name':'cpu_pct','value':30.0,'unit':'%'},'health_state':'Excellent','collector_version':'1.0'}
    raw=json.dumps(payload,separators=(',',':')).encode(); sig=hmac.new(os.getenv('DEMO_SECRET','local_secret').encode(),raw,hashlib.sha256).hexdigest()
    req=urllib.request.Request(a.url+'/v1/ingest',data=raw,headers={'X-Collector-Key':os.getenv('DEMO_KEY','c1'),'X-Signature':sig,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=10) as response: print(response.read().decode())
    req=urllib.request.Request(a.url+'/v1/proof',headers={'Authorization':'Bearer '+os.getenv('DEMO_DASHBOARD_KEY','d1')})
    with urllib.request.urlopen(req,timeout=10) as response: print(response.read().decode())
if __name__=='__main__': main()
