"""Local synthetic load probe; run only against a disposable test deployment.

Credentials are read from a JSON file (never printed). Example:
python -m saas.tools.loadtest --url http://127.0.0.1:8000 --credentials /tmp/load-credentials.json --per-collector 20
The JSON is an array of {tenant,region,collector,key,secret}; all values must
match the target test server's configured collector credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.request
import uuid


def send(url, credential, i):
    payload = {
        'payload_id': str(uuid.uuid4()), 'tenant_ref': credential['tenant'],
        'collector_id': credential['collector'], 'source_id': 'src_12345678',
        'region': credential['region'], 'event_ts_utc': datetime.now(timezone.utc).isoformat(),
        'source_tz': 'UTC', 'window_s': 5, 'metric': {'name': 'cpu_pct', 'value': 20 + i % 2, 'unit': '%'},
        'health_state': 'Excellent', 'collector_version': '1.0.0',
    }
    body = json.dumps(payload, separators=(',', ':')).encode()
    signature = hmac.new(credential['secret'].encode(), body, hashlib.sha256).hexdigest()
    request = urllib.request.Request(url.rstrip('/')+'/v1/ingest', data=body, headers={
        'Content-Type': 'application/json', 'X-Collector-Key': credential['key'], 'X-Signature': signature,
    })
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
            ok = response.status == 200 and payload['payload_id'] in result['accepted']
    except (OSError, urllib.error.HTTPError, ValueError): ok = False
    return ok, time.perf_counter()-start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--credentials', required=True, help='JSON file with synthetic credentials')
    parser.add_argument('--per-collector', type=int, default=20)
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    credentials = json.loads(Path(args.credentials).read_text())
    if not isinstance(credentials, list) or not credentials or not 1 <= args.per_collector <= 10000 or not 1 <= args.workers <= 100:
        parser.error('Provide a nonempty credential list, 1–10000 payloads, and 1–100 workers')
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(send,args.url,c,i) for c in credentials for i in range(args.per_collector)]
        results = [f.result() for f in futures]
    elapsed = time.perf_counter()-start
    durations = sorted(t for ok,t in results if ok)
    p95 = durations[max(0, int(len(durations)*.95 + .999)-1)] if durations else None
    print(json.dumps({'collectors':len(credentials),'tenants':len({c['tenant'] for c in credentials}),
        'attempted':len(results),'accepted':len(durations),'failed':len(results)-len(durations),
        'seconds':round(elapsed,3),'accepted_per_s':round(len(durations)/elapsed,2),
        'client_p95_s':round(p95,4) if p95 is not None else None,'workers':args.workers,
        'note':'Client-observed synthetic ingest only; not end-to-end latency or a production capacity claim.'}, indent=2))

if __name__ == '__main__': main()
