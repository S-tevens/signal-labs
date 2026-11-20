import hashlib,hmac,json,os
from dataclasses import dataclass
from fastapi import HTTPException, Request
@dataclass(frozen=True)
class Principal:
    tenant: str
    region: str
    role: str
    collector: str|None = None
class Auth:
    def __init__(self, region, config=None, store=None):
        self.region=region
        self.store=store
        self.config=config if config is not None else json.loads(os.getenv('SAAS_AUTH_JSON','{}'))
    def collector(self,request:Request,body:bytes):
        key=request.headers.get('X-Collector-Key',''); sig=request.headers.get('X-Signature','')
        rec=self.config.get('collectors',{}).get(key) if key else None
        # Enrolled keys carry an untrusted tenant hint. The authenticated record,
        # never the payload or hint alone, determines collector identity.
        if not rec and self.store and '.' in key and len(key) <= 256:
            from .enroll import TENANT, digest
            hint=key.split('.',1)[0]
            if TENANT.fullmatch(hint):
                with self.store.connect(hint) as db:
                    row=db.execute('SELECT collector_id,region,signing_secret FROM collector_credentials WHERE key_hash=? AND active=TRUE',(digest(key),)).fetchone()
                    if row: rec={'tenant':hint,'region':row['region'],'collector':row['collector_id'],'secret':row['signing_secret']}
        if not rec: raise HTTPException(401,'Invalid collector credentials')
        expected=hmac.new(rec['secret'].encode(),body,hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,sig.removeprefix('sha256=')): raise HTTPException(401,'Invalid signature')
        if rec['region']!=self.region: raise HTTPException(403,'Wrong region')
        return Principal(rec['tenant'],rec['region'],'collector',rec['collector'])
    def dashboard(self,request:Request):
        scheme,_,key=request.headers.get('Authorization','').partition(' ')
        rec=self.config.get('dashboard',{}).get(key) if scheme.lower()=='bearer' and key else None
        if not rec: raise HTTPException(401,'Invalid dashboard credentials')
        if rec['region']!=self.region: raise HTTPException(403,'Wrong region')
        return Principal(rec['tenant'],rec['region'],rec.get('role','viewer'))
