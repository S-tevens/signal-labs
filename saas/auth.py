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
    def __init__(self, region, config=None):
        self.region=region
        self.config=config if config is not None else json.loads(os.getenv('SAAS_AUTH_JSON','{}'))
    def collector(self,request:Request,body:bytes):
        key=request.headers.get('X-Collector-Key',''); sig=request.headers.get('X-Signature','')
        rec=self.config.get('collectors',{}).get(key) if key else None
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
