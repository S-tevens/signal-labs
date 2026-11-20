"""One-time enrollment. Credentials are returned once; never log request bodies."""
import hashlib
import re
import secrets
import time
from fastapi import HTTPException
from .store import audit, utc

TENANT = re.compile(r'^t-[a-z0-9-]{1,40}$')
COLLECTOR = re.compile(r'^col-[a-z0-9-]{1,40}$')

def digest(value): return hashlib.sha256(value.encode()).hexdigest()

def create_token(db, who, body):
    if who.role != 'admin': raise HTTPException(403, 'Admin role required')
    if not isinstance(body,dict) or set(body)-{'collector_id','expires_in_s'} or 'collector_id' not in body:
        raise HTTPException(422,'Expected collector_id and optional expires_in_s')
    collector=body['collector_id']; ttl=body.get('expires_in_s',900)
    if not isinstance(collector,str) or not COLLECTOR.fullmatch(collector) or type(ttl) is not int or not 60<=ttl<=3600:
        raise HTTPException(422,'Invalid collector ID or expiration')
    token=secrets.token_urlsafe(32); expires=time.time()+ttl
    db.execute('INSERT INTO enrollment_tokens(token_hash,collector_id,region,expires_at) VALUES(?,?,?,?)',(digest(token),collector,who.region,expires))
    audit(db,'enrollment_token_created',collector,{'role':who.role,'expires_at':utc(expires)})
    return {'tenant_ref':who.tenant,'collector_id':collector,'token':token,'expires_at':utc(expires),'region':who.region}

def enroll(store, region, body):
    if not isinstance(body,dict) or set(body)!={'tenant_ref','token'} or not isinstance(body['tenant_ref'],str) or not TENANT.fullmatch(body['tenant_ref']) or not isinstance(body['token'],str) or not 20<=len(body['token'])<=128:
        raise HTTPException(422,'Expected tenant_ref and enrollment token')
    tenant=body['tenant_ref']; now=time.time()
    with store.connect(tenant) as db:
        row=db.execute('UPDATE enrollment_tokens SET used_at=? WHERE token_hash=? AND region=? AND used_at IS NULL AND expires_at>? RETURNING collector_id,region',(now,digest(body['token']),region,now)).fetchone()
        if not row: raise HTTPException(401,'Invalid or expired enrollment token')
        key=tenant+'.'+secrets.token_urlsafe(32); secret=secrets.token_urlsafe(48)
        db.execute('INSERT INTO collector_credentials(key_hash,collector_id,region,signing_secret,created_at) VALUES(?,?,?,?,?)',(digest(key),row['collector_id'],region,secret,utc(now)))
        audit(db,'collector_enrolled',row['collector_id'],{'region':region})
        return {'collector_id':row['collector_id'],'tenant_ref':tenant,'region':region,'collector_key':key,'collector_secret':secret,'note':'Credentials are returned once. Store them locally and use TLS.'}
