import hashlib,hmac,json,os
from . import users
from dataclasses import dataclass
from fastapi import HTTPException, Request
@dataclass(frozen=True)
class Principal:
    tenant: str
    region: str
    role: str
    collector: str|None = None
    user: str|None = None          # the signed-in person (None for an API token or a collector)
    must_change: bool = False      # a temporary password is still in force
    display_name: str|None = None
class Auth:
    def __init__(self, region, config=None, store=None):
        self.region=region
        self.store=store
        self.config=config if config is not None else json.loads(os.getenv('SAAS_AUTH_JSON','{}'))
        self.session_secret=os.getenv('SAAS_SESSION_SECRET','') or None   # signs sign-in sessions; every replica must share it
        self.api_tokens=os.getenv('SAAS_DISABLE_API_TOKENS')!='1'          # static tokens: for scripts and dev; switch off in production
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
    def _session(self,token):
        claims=users.read_token(self.session_secret,token) if self.session_secret else None
        if not claims or not self.store or not isinstance(claims.get('t'),str) or not isinstance(claims.get('u'),str): raise HTTPException(401,'Your session has ended. Sign in again.')
        with self.store.connect(claims['t'],lock=False) as db: row=users.get_user(db,claims['u'])
        # The role is read now, not taken from the token: a change by an administrator applies to the very next request.
        if not row or not row['active'] or row['token_version']!=claims.get('v'): raise HTTPException(401,'Your session has ended. Sign in again.')
        return Principal(claims['t'],self.region,row['role'],None,row['username'],bool(row['must_change_password']),row['display_name'])
    def dashboard(self,request:Request):
        scheme,_,key=request.headers.get('Authorization','').partition(' ')
        if scheme.lower()=='bearer' and key.startswith(users.TOKEN_PREFIX): return self._session(key)
        rec=self.config.get('dashboard',{}).get(key) if scheme.lower()=='bearer' and key and self.api_tokens else None
        if not rec: raise HTTPException(401,'Invalid dashboard credentials')
        if rec['region']!=self.region: raise HTTPException(403,'Wrong region')
        return Principal(rec['tenant'],rec['region'],rec.get('role','viewer'))
