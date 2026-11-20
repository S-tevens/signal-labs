import React, { useEffect, useState } from 'react';
import { request, LIVE } from './api';

const TYPES = ['tenant', 'collector', 'source', 'observation', 'incident', 'recommendation', 'action'];
const labels = { restart_service: 'Restart service', isolate_source: 'Isolate source', rotate_credentials: 'Rotate credentials', scale_capacity: 'Scale capacity' };
const path = (type, id) => `/v1/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}`;

function Message({ children }) { return <div className="platform-message" role="status">{children}</div>; }
function ObjectDetails({ selected, onSelect }) {
  const [obj, setObj] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    if (!selected || !LIVE) return;
    const ctrl = new AbortController(); setObj(null); setError('');
    request(path(selected.type, selected.id), { signal: ctrl.signal }).then(setObj).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => ctrl.abort();
  }, [selected?.type, selected?.id]);
  if (!selected) return null;
  if (error) return <Message>Object could not be loaded: {error}</Message>;
  if (!obj) return <Message>Loading object…</Message>;
  const links = { collector: 'collector', collectors: 'collector', source: 'source', sources: 'source', observations: 'observation', recommendation: 'recommendation', incident: 'incident', actions: 'action' };
  return <div className="platform-object"><div className="platform-object-head"><strong>{obj.type} · {obj.id}</strong><button className="button small" onClick={() => onSelect(null)}>Close object</button></div>
    <pre>{JSON.stringify(obj.properties, null, 2)}</pre>
    <div className="platform-links">{Object.entries(obj.links || {}).flatMap(([label, value]) => (Array.isArray(value) ? value : [value]).filter(Boolean).map(id => <button className="button small" key={`${label}-${id}`} onClick={() => onSelect({type: links[label], id})}>{label}: {id}</button>))}</div>
  </div>;
}
export function ObjectExplorer() {
  const [type, setType] = useState('incident'), [objects, setObjects] = useState([]), [selected, setSelected] = useState(null), [error, setError] = useState(''), [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!LIVE) return;
    const ctrl = new AbortController(); setLoading(true); setError(''); setSelected(null);
    request(`/v1/objects/${type}`, {signal:ctrl.signal}).then(setObjects).catch(e => { if(e.name !== 'AbortError') setError(e.message); }).finally(() => { if(!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [type]);
  if (!LIVE) return <section className="panel platform-panel"><h2>Object explorer</h2><p>Connect the SaaS to explore real tenant-scoped objects and their links.</p></section>;
  return <section className="panel platform-panel"><h2>Object explorer</h2><p>Explore your tenant’s metadata and links between incidents, sources, and evidence.</p>
    <label className="platform-label">Object type <select value={type} onChange={e => setType(e.target.value)}>{TYPES.map(t => <option value={t} key={t}>{t}</option>)}</select></label>
    {loading && <Message>Loading objects…</Message>}{error && <Message>Could not load objects: {error}</Message>}
    {!loading && !error && <div className="platform-object-list">{objects.length ? objects.map(o => <button key={o.id} className="platform-list-item" onClick={() => setSelected({type:o.type,id:o.id})}>{o.id} <span>View object</span></button>) : <Message>No {type} objects found.</Message>}</div>}
    <ObjectDetails selected={selected} onSelect={setSelected}/>
  </section>;
}
export function HealthHistory() {
  const [rows, setRows] = useState([]), [error, setError] = useState(''), [loading, setLoading] = useState(LIVE);
  useEffect(() => { if (!LIVE) return; const ctrl=new AbortController(); request('/v1/health/history',{signal:ctrl.signal}).then(setRows).catch(e => { if(e.name!=='AbortError') setError(e.message); }).finally(() => { if(!ctrl.signal.aborted) setLoading(false); }); return () => ctrl.abort(); }, []);
  return <section className="panel platform-panel"><h2>Health history</h2><p>Collector state changes and reasons, recorded in UTC.</p>{!LIVE ? <Message>Connect the SaaS to view recorded state changes.</Message> : loading ? <Message>Loading history…</Message> : error ? <Message>History could not be loaded: {error}</Message> : rows.length ? <div className="platform-object-list">{rows.map(r => <div className="platform-history" key={r.id}><strong>{r.collector} · {r.state}</strong><span>{r.ts} · {r.reason}</span></div>)}</div> : <Message>No health transitions recorded.</Message>}</section>;
}
export function IncidentWorkspace({ incidentId, mode }) {
  const [lineage, setLineage] = useState(null), [actions, setActions] = useState([]), [catalog, setCatalog] = useState({}), [error, setError] = useState(''), [selected, setSelected] = useState(null), [type, setType] = useState('restart_service'), [service, setService] = useState(''), [credential, setCredential] = useState(''), [replicas, setReplicas] = useState(2), [busy, setBusy] = useState(false);
  async function load(signal) {
    try { const [l, a] = await Promise.all([request(`/v1/lineage/incident/${encodeURIComponent(incidentId)}`,{signal}), request(`/v1/actions?incident_id=${encodeURIComponent(incidentId)}`,{signal})]); setLineage(l); setActions(a.actions); setCatalog(a.types); setError(''); }
    catch(e) { if(e.name !== 'AbortError') setError(e.message); }
  }
  useEffect(() => { if(mode !== 'live') return; const ctrl=new AbortController(); load(ctrl.signal); return () => ctrl.abort(); }, [incidentId,mode]);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const params = type === 'isolate_source' ? {source_id:lineage?.source_id} : type === 'rotate_credentials' ? {credential_ref:credential} : type === 'scale_capacity' ? {service, replicas:Number(replicas)} : {service};
    try { await request('/v1/actions/propose',{method:'POST',body:{incident_id:incidentId,action_type:type,parameters:params}}); await load(); }
    catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  async function transition(id, operation) { setBusy(true); setError(''); try { await request(`/v1/actions/${encodeURIComponent(id)}/${operation}`,{method:'POST'}); await load(); } catch(e) { setError(e.message); } finally { setBusy(false); } }
  if(mode !== 'live') return <div className="platform-workspace"><h3>Evidence & simulated actions</h3><Message>Connect the SaaS to inspect actual payload lineage and propose actions.</Message></div>;
  return <div className="platform-workspace"><h3>Evidence & lineage</h3>{error && <Message>{error}</Message>}{!lineage ? <Message>Loading evidence…</Message> : <><p>Raw records remain local. Follow these metadata objects to see the evidence behind this recommendation.</p><div className="platform-links"><button className="button small" onClick={() => setSelected({type:'collector',id:lineage.collector_id})}>Collector · {lineage.collector_id}</button><button className="button small" onClick={() => setSelected({type:'source',id:lineage.source_id})}>Source · {lineage.source_id}</button>{lineage.payload_ids.map(id => <button className="button small" key={id} onClick={() => setSelected({type:'observation',id})}>Payload · {id}</button>)}<button className="button small" onClick={() => setSelected({type:'recommendation',id:incidentId})}>Recommendation</button></div><p className="platform-hint">{lineage.note}</p></>}
    <ObjectDetails selected={selected} onSelect={setSelected}/><h3>Simulated actions</h3><p>Propose an action for operator review. No infrastructure commands are executed.</p>
    <form onSubmit={submit} className="platform-form"><label>Action type<select value={type} onChange={e => setType(e.target.value)}>{Object.keys(catalog).map(t => <option key={t} value={t}>{labels[t] || t}</option>)}</select></label>
      {['restart_service','scale_capacity'].includes(type) && <label>Service name<input value={service} required maxLength="64" pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" onChange={e => setService(e.target.value)} placeholder="api-service"/></label>}
      {type === 'rotate_credentials' && <label>Credential reference<input value={credential} required maxLength="64" pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,63}" onChange={e => setCredential(e.target.value)} placeholder="service-account"/></label>}
      {type === 'scale_capacity' && <label>Replicas<input type="number" min="1" max="20" required value={replicas} onChange={e => setReplicas(e.target.value)}/></label>}
      {type === 'isolate_source' && <p>Source: {lineage?.source_id || 'loading…'}</p>}
      <button className="button" type="submit" disabled={busy || !lineage || !Object.keys(catalog).length}>Propose simulation</button></form>
    {actions.length === 0 ? <Message>No actions proposed for this incident.</Message> : actions.map(a => <Action key={a.id} action={a} busy={busy} transition={transition}/>)}
  </div>;
}
function Action({action, busy, transition}) {
  const [details, setDetails] = useState(null), [error, setError] = useState('');
  useEffect(() => { const ctrl=new AbortController(); request(`/v1/actions/${encodeURIComponent(action.id)}`,{signal:ctrl.signal}).then(setDetails).catch(e => { if(e.name!=='AbortError') setError(e.message); }); return () => ctrl.abort(); }, [action.id,action.updated_at]);
  return <article className="platform-action"><strong>{labels[action.action_type] || action.action_type} · {action.status}</strong><p>{action.rollback_plan}</p><div className="platform-links">{action.status === 'proposed' && <><button className="button small" disabled={busy} onClick={() => transition(action.id,'approve')}>Approve simulation</button><button className="button small" disabled={busy} onClick={() => transition(action.id,'reject')}>Reject</button></>}{action.status === 'approved' && <button className="button small" disabled={busy} onClick={() => transition(action.id,'rollback')}>Record rollback</button>}</div>{error && <Message>{error}</Message>}{details && <ol className="platform-audit">{details.audit.map(entry => <li key={entry.id}>{entry.ts} · {entry.action} · {entry.detail.role}</li>)}</ol>}</article>;
}
