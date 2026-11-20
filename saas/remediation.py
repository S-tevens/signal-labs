import json
from fastapi import HTTPException
from .store import audit,dump,utc

def approve(db,ident,principal):
    if principal.role!='operator': raise HTTPException(403,'Operator role required')
    row=db.execute('SELECT data FROM incidents WHERE id=?',(ident,)).fetchone()
    if not row: raise HTTPException(404,'Incident not found')
    obj=json.loads(row['data'])
    if obj.get('remediation'): return obj['remediation']
    result={'status':'simulated','policy':'simulation only; no source commands are executed','approved_at':utc(),'action':obj['recommendation']['action'],'rollback':'No infrastructure changes made; discard simulated action record.'}
    obj['remediation']=result; db.execute('UPDATE incidents SET data=? WHERE id=?',(dump(obj),ident)); audit(db,'remediation_approved',ident,result); return result
