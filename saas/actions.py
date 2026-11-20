"""Policy-bounded simulated actions. No infrastructure commands are executed."""
import json
import re
import uuid
from fastapi import HTTPException
from .store import audit, dump, utc

TYPES = {
    'restart_service': {'label': 'Restart service', 'parameters': ['service'], 'rollback': 'No service was restarted. Discard the simulation; for a real change, restore the previous known-good service state.'},
    'isolate_source': {'label': 'Isolate source', 'parameters': ['source_id'], 'rollback': 'No network policy was changed. For a real change, restore the prior network policy.'},
    'rotate_credentials': {'label': 'Rotate credentials', 'parameters': ['credential_ref'], 'rollback': 'No credentials were changed. For a real rotation, follow the documented credential recovery procedure.'},
    'scale_capacity': {'label': 'Scale capacity', 'parameters': ['service', 'replicas'], 'rollback': 'No capacity was changed. For a real change, restore the previous replica count.'},
}
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
SOURCE = re.compile(r'^src_[0-9a-f]{8,16}$')

def require_operator(who):
    if who.role not in {'operator', 'admin'}:
        raise HTTPException(403, 'Operator role required')

def clean(row):
    if not row: return None
    return {**{k: v for k, v in row.items() if k != 'tenant_id'}, 'parameters': json.loads(row['parameters']), 'simulation_only': True}

def list_actions(db, incident_id=None):
    if incident_id:
        rows = db.execute('SELECT * FROM actions WHERE incident_id=? ORDER BY created_at DESC,id', (incident_id,))
    else:
        rows = db.execute('SELECT * FROM actions ORDER BY created_at DESC,id LIMIT 500')
    return [clean(r) for r in rows]

def propose(db, who, body):
    require_operator(who)
    if not isinstance(body, dict) or set(body) != {'incident_id', 'action_type', 'parameters'}:
        raise HTTPException(422, 'Expected incident_id, action_type and parameters')
    incident_id, kind, params = body['incident_id'], body['action_type'], body['parameters']
    if not isinstance(incident_id, str) or not isinstance(kind, str) or kind not in TYPES or not isinstance(params, dict) or set(params) != set(TYPES[kind]['parameters']):
        raise HTTPException(422, 'Invalid action type or parameters')
    for key, value in params.items():
        if key == 'replicas':
            if type(value) is not int or not 1 <= value <= 20: raise HTTPException(422, 'replicas must be an integer from 1 to 20')
        elif not isinstance(value, str) or not (SOURCE if key == 'source_id' else NAME).fullmatch(value):
            raise HTTPException(422, 'Invalid action parameter')
    incident_row = db.execute('SELECT data FROM incidents WHERE id=?', (incident_id,)).fetchone()
    if not incident_row: raise HTTPException(404, 'Incident not found')
    incident = json.loads(incident_row['data'])
    if kind == 'isolate_source' and params['source_id'] != incident['source_id']:
        raise HTTPException(422, 'Source must match the incident')
    ident, now = str(uuid.uuid4()), utc()
    db.execute('INSERT INTO actions(id,incident_id,action_type,parameters,status,proposed_by,created_at,updated_at,rollback_plan) VALUES(?,?,?,?,?,?,?,?,?)',
               (ident, incident_id, kind, dump(params), 'proposed', who.role, now, now, TYPES[kind]['rollback']))
    audit(db, 'action_proposed', ident, {'role': who.role, 'actor': who.user or 'api-token', 'incident_id': incident_id, 'action_type': kind, 'simulation_only': True})
    return get_action(db, ident)

def get_action(db, ident):
    row = db.execute('SELECT * FROM actions WHERE id=?', (ident,)).fetchone()
    if not row: raise HTTPException(404, 'Action not found')
    result = clean(row)
    result['audit'] = [{**{k: v for k, v in r.items() if k not in ('tenant_id', 'detail')}, 'detail': json.loads(r['detail'])} for r in db.execute('SELECT * FROM audit WHERE reference=? ORDER BY id', (ident,))]
    return result

def transition(db, who, ident, operation):
    require_operator(who)
    action = get_action(db, ident)
    transitions = {'approve': ('proposed', 'approved'), 'reject': ('proposed', 'rejected'), 'rollback': ('approved', 'rolled_back')}
    if operation not in transitions: raise HTTPException(404, 'Unknown operation')
    expected, result = transitions[operation]
    if action['status'] != expected: raise HTTPException(409, 'Invalid action transition')
    now = utc()
    db.execute('UPDATE actions SET status=?,updated_at=? WHERE id=?', (result, now, ident))
    audit(db, 'action_' + result, ident, {'role': who.role, 'actor': who.user or 'api-token', 'simulation_only': True, 'rollback_plan': action['rollback_plan'] if operation == 'rollback' else None})
    return get_action(db, ident)
