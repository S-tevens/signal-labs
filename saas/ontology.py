"""Typed, tenant-scoped views over existing metadata (never collector raw records)."""
import json
from fastapi import HTTPException
from .actions import get_action, list_actions

REGISTRY = {
    'types': {
        'tenant': {'properties': {'id': 'ALLOWED_METADATA', 'region': 'ALLOWED_METADATA'}},
        'collector': {'properties': {'id': 'ALLOWED_METADATA', 'state': 'ALLOWED_METADATA'}},
        'source': {'properties': {'id': 'PSEUDONYMIZED'}},
        'observation': {'properties': {'payload_id': 'ALLOWED_METADATA', 'source_id': 'PSEUDONYMIZED'}},
        'incident': {'properties': {'id': 'ALLOWED_METADATA', 'signals': 'ALLOWED_METADATA'}},
        'recommendation': {'properties': {'incident_id': 'ALLOWED_METADATA', 'why': 'ALLOWED_METADATA'}},
        'action': {'properties': {'id': 'ALLOWED_METADATA', 'status': 'ALLOWED_METADATA'}},
    },
    'links': ['tenant->collector', 'collector->source', 'source->observation', 'incident->collector', 'incident->source', 'incident->observation', 'incident->recommendation', 'incident->action'],
    'boundary': 'Raw records and local redaction lineage remain on the collector.',
}

def item(kind, ident, data, links=None):
    return {'type': kind, 'id': ident, 'properties': data, 'links': links or {}}

def list_objects(db, who, kind):
    if kind not in REGISTRY['types']: raise HTTPException(404, 'Unknown object type')
    if kind == 'tenant': return [item(kind, who.tenant, {'region': who.region})]
    if kind == 'collector': return [item(kind, r['id'], {k:v for k,v in r.items() if k not in ('tenant_id', 'id')}) for r in db.execute('SELECT * FROM fleet ORDER BY id LIMIT 500')]
    if kind == 'source': return [item(kind, r['source'], {'collectors': r['collectors']}) for r in db.execute('SELECT source,COUNT(DISTINCT collector) AS collectors FROM payloads GROUP BY source ORDER BY source LIMIT 500')]
    if kind == 'observation': return [item(kind, r['id'], json.loads(r['data'])) for r in db.execute('SELECT id,data FROM payloads ORDER BY ts DESC LIMIT 500')]
    if kind == 'incident': return [item(kind, r['id'], json.loads(r['data'])) for r in db.execute('SELECT id,data FROM incidents ORDER BY last_ts DESC LIMIT 500')]
    if kind == 'recommendation': return [item(kind, r['id'], json.loads(r['data']).get('recommendation', {})) for r in db.execute('SELECT id,data FROM incidents ORDER BY last_ts DESC LIMIT 500')]
    return [item(kind, r['id'], r) for r in list_actions(db)]

def object_detail(db, who, kind, ident):
    if kind not in REGISTRY['types']: raise HTTPException(404, 'Unknown object type')
    if kind == 'tenant':
        if ident != who.tenant: raise HTTPException(404, 'Object not found')
        return item(kind, ident, {'region': who.region}, {'collectors': [x['id'] for x in list_objects(db, who, 'collector')]})
    if kind == 'collector':
        row = db.execute('SELECT * FROM fleet WHERE id=?', (ident,)).fetchone()
        if not row: raise HTTPException(404, 'Object not found')
        sources = [r['source'] for r in db.execute('SELECT DISTINCT source FROM payloads WHERE collector=? ORDER BY source', (ident,))]
        return item(kind, ident, {k:v for k,v in row.items() if k not in ('tenant_id','id')}, {'sources': sources})
    if kind == 'source':
        rows = db.execute('SELECT id,collector FROM payloads WHERE source=? ORDER BY ts DESC LIMIT 500', (ident,)).fetchall()
        if not rows: raise HTTPException(404, 'Object not found')
        return item(kind, ident, {}, {'collectors': sorted({r['collector'] for r in rows}), 'observations': [r['id'] for r in rows]})
    if kind == 'observation':
        row = db.execute('SELECT data FROM payloads WHERE id=?', (ident,)).fetchone()
        if not row: raise HTTPException(404, 'Object not found')
        data = json.loads(row['data'])
        return item(kind, ident, data, {'collector': data['collector_id'], 'source': data['source_id']})
    if kind in {'incident', 'recommendation'}:
        row = db.execute('SELECT data FROM incidents WHERE id=?', (ident,)).fetchone()
        if not row: raise HTTPException(404, 'Object not found')
        incident = json.loads(row['data'])
        if kind == 'recommendation': return item(kind, ident, incident.get('recommendation', {}), {'incident': ident})
        payloads = list(dict.fromkeys(s['payload_id'] for s in incident.get('signals', []) if s.get('payload_id')))
        return item(kind, ident, incident, {'collector': incident['collector_id'], 'source': incident['source_id'], 'observations': payloads, 'recommendation': ident, 'actions': [a['id'] for a in list_actions(db, ident)]})
    action = get_action(db, ident)
    return item(kind, ident, action, {'incident': action['incident_id']})

def incident_lineage(db, who, ident):
    incident = object_detail(db, who, 'incident', ident)
    props = incident['properties']
    return {'incident_id': ident, 'collector_id': props['collector_id'], 'source_id': props['source_id'], 'signals': props.get('signals', []), 'payload_ids': incident['links']['observations'], 'recommendation': props.get('recommendation'), 'note': 'Only retained incident signals are shown; raw records stay on the collector.'}

def payload_lineage(db, who, ident):
    obj = object_detail(db, who, 'observation', ident)
    matches = []
    # Incident signal lists are capped at 100. Do not claim historical completeness.
    for row in db.execute('SELECT id,data FROM incidents WHERE collector=? AND source=? ORDER BY last_ts DESC', (obj['links']['collector'], obj['links']['source'])):
        incident = json.loads(row['data'])
        signals = [s for s in incident.get('signals', []) if s.get('payload_id') == ident]
        if signals: matches.append({'incident_id': row['id'], 'signals': signals})
    return {'payload_id': ident, 'collector_id': obj['links']['collector'], 'source_id': obj['links']['source'], 'incidents': matches, 'note': 'Only retained incident signals are searched.'}
