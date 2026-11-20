import React, { useEffect, useRef, useState } from 'react';
import { request, LIVE, currentToken } from './api';

const TYPES = ['tenant', 'collector', 'source', 'observation', 'incident', 'recommendation', 'action'];
const labels = { restart_service: 'Restart service', isolate_source: 'Isolate source', rotate_credentials: 'Rotate credentials', scale_capacity: 'Scale capacity' };
const path = (type, id) => `/v1/objects/${encodeURIComponent(type)}/${encodeURIComponent(id)}`;

function Message({ children }) { return <div className="platform-message" role="status">{children}</div>; }
// A long list that starts short. "Show all" opens the full list; while it is open a bar with "Show less" stays pinned at
// the top of the scrolling panel, and there is another button under the list, so collapsing is never a long scroll away.
function ExpandableList({ items, limit = 4, noun = 'items', className }) {
  const [open, setOpen] = useState(false);
  const top = useRef(null);
  const total = items.length;
  if (total <= limit) return <div className={className}>{items}</div>;
  const collapse = () => { setOpen(false); requestAnimationFrame(() => requestAnimationFrame(() => top.current?.scrollIntoView({ block: 'start' }))); };  // after the shorter list is drawn, bring it back into view
  return <div className="expandable" ref={top}>
    {open && <div className="expandable-bar" role="status"><span>Showing all {total} {noun}</span><button type="button" className="button small secondary" onClick={collapse}>Show less</button></div>}
    <div className={className}>{open ? items : items.slice(0, limit)}</div>
    <div className="expandable-foot">
      {open ? <button type="button" className="button small secondary" onClick={collapse}>Show less</button>
        : <button type="button" className="button small" onClick={() => setOpen(true)} aria-expanded="false">Show all {total} {noun}<span className="expandable-more">{total - limit} more</span></button>}
    </div>
  </div>;
}

function SignalSummary({ signals }) {
  const counts = signals.reduce((m, s) => { const k = (s.signal || 'unknown').replaceAll('_', ' '); m[k] = (m[k] || 0) + 1; return m; }, {});
  return <p className="signal-summary">{signals.length} retained signals: {Object.entries(counts).map(([k, n]) => `${k} ×${n}`).join(', ')}</p>;
}

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
export function ReceivedPayload() {
  const initial = new URLSearchParams(location.hash.split('?')[1] || '').get('id') || '';
  const [id,setId] = useState(initial), [submitted,setSubmitted] = useState(initial), [payload,setPayload] = useState(null), [error,setError] = useState(''), [loading,setLoading] = useState(false);
  useEffect(() => {
    const update=()=>{ const next=new URLSearchParams(location.hash.split('?')[1] || '').get('id') || ''; setId(next); setSubmitted(next); };
    window.addEventListener('hashchange',update); return ()=>window.removeEventListener('hashchange',update);
  }, []);
  useEffect(() => {
    if (!LIVE || !submitted) { setPayload(null); return; }
    const ctrl=new AbortController(); setPayload(null); setError(''); setLoading(true);
    request(path('observation',submitted),{signal:ctrl.signal}).then(setPayload).catch(e=>{if(e.name !== 'AbortError') setError(e.message);}).finally(()=>{if(!ctrl.signal.aborted)setLoading(false);});
    return ()=>ctrl.abort();
  },[submitted]);
  return <section className="panel platform-panel received-page"><h2>Received payload</h2><p>Enter the payload ID from the collector’s local egress panel to inspect the matching metadata in your tenant.</p><form className="received-search" onSubmit={e=>{e.preventDefault(); setSubmitted(id.trim());}}><label htmlFor="received-id">Payload ID</label><div><input id="received-id" value={id} onChange={e=>setId(e.target.value)} placeholder="Paste a payload ID" required/><button className="button" disabled={!LIVE || !id.trim()} type="submit">Find payload</button></div></form><p className="platform-hint">These are validated, normalized stored fields. Formatting and timestamps can differ from the original transmitted bytes; compare fields with the collector’s egress panel.</p>{!LIVE ? <Message>Connect the SaaS to inspect a received payload.</Message> : loading ? <Message>Loading payload…</Message> : error ? <Message>Could not find this payload for the current tenant: {error}</Message> : payload ? <div className="platform-object"><div className="platform-object-head"><strong>Stored observation · {payload.id}</strong></div><pre>{JSON.stringify(payload.properties,null,2)}</pre></div> : <Message>Enter a payload ID to begin.</Message>}</section>;
}

function SignalEvidence({lineage}) {
  const signals=lineage?.signals || [];
  if (!signals.length) return <Message>No retained signal details are available for this incident.</Message>;
  return <div className="signal-evidence"><h3>Why was it flagged?</h3><p>Retained incident signals, in event-time order. A recommendation is an investigation hypothesis, not proof of cause.</p><SignalSummary signals={signals}/><ExpandableList className="signal-evidence-list" noun="signals" limit={3} items={signals.map((s,i)=><article className="signal-evidence-card" key={`${s.payload_id || 'signal'}-${i}`}><div><strong>{(s.signal || 'Unknown signal').replaceAll('_',' ')}</strong><span>{s.severity || 'Severity unavailable'}</span></div><p>{s.why || 'Detection reason unavailable.'}</p><dl><div><dt>Observed</dt><dd>{s.value == null ? 'Unavailable' : `${s.value}${s.unit ? ` ${s.unit}` : ''}`}</dd></div><div><dt>Method</dt><dd>{s.method || 'Unavailable'}</dd></div><div><dt>Baseline</dt><dd>{s.baseline == null ? 'Not recorded' : `${s.baseline}${s.samples != null ? ` (${s.samples} samples)` : ''}`}</dd></div><div><dt>Threshold</dt><dd>{s.threshold == null ? 'Not recorded' : `${s.comparison || ''} ${s.threshold}`}</dd></div><div><dt>Event time (UTC)</dt><dd>{s.event_ts_utc || 'Not recorded'}</dd></div><div><dt>Alert time (UTC)</dt><dd>{s.alert_ts_utc || 'Not recorded for this signal'}</dd></div><div><dt>Persistence</dt><dd>{s.persistence_windows == null ? 'Not recorded / not applicable' : `${s.persistence_windows} windows`}</dd></div></dl>{s.payload_id && <a href={`#/received?id=${encodeURIComponent(s.payload_id)}`}>Inspect payload · {s.payload_id}</a>}</article>)}/></div>;
}
function Thresholds() {
  const [data,setData] = useState(null), [error,setError] = useState('');
  useEffect(() => {
    if (!LIVE) return;
    const ctrl=new AbortController();
    request('/v1/health/thresholds',{signal:ctrl.signal}).then(setData).catch(e=>{if(e.name !== 'AbortError') setError(e.message);});
    return () => ctrl.abort();
  }, []);
  return <div className="health-thresholds"><h3>Configured health thresholds</h3>{!LIVE ? <Message>Connect the SaaS to view its thresholds.</Message> : error ? <Message>Thresholds unavailable: {error}</Message> : !data ? <Message>Loading thresholds…</Message> : <><p>Heartbeat is stale after {data.stale_after_s}s and offline after {data.offline_after_s}s. Thresholds use the units supplied by each metric.</p><div className="threshold-grid">{Object.entries(data.metrics).filter(([,r]) => r.poor !== undefined).map(([name,r]) => <div key={name}><strong>{name.replaceAll('_',' ')}</strong><span>Good {r.inverse ? '<' : '≥'} {r.good} · Fair {r.inverse ? '≤' : '≥'} {r.fair} · Poor {r.inverse ? '≤' : '≥'} {r.poor}</span></div>)}</div><p>Excellent means the value is better than the Good threshold. Other signals and heartbeat age can also affect health.</p></>}</div>;
}
export function HealthHistory() {
  const [rows, setRows] = useState([]), [error, setError] = useState(''), [loading, setLoading] = useState(LIVE);
  useEffect(() => { if (!LIVE) return; const ctrl=new AbortController(); request('/v1/health/history',{signal:ctrl.signal}).then(setRows).catch(e => { if(e.name!=='AbortError') setError(e.message); }).finally(() => { if(!ctrl.signal.aborted) setLoading(false); }); return () => ctrl.abort(); }, []);
  return <section className="panel platform-panel"><h2>Health history</h2><p>Collector state changes and reasons, recorded in UTC.</p><Thresholds/>{!LIVE ? <Message>Connect the SaaS to view recorded state changes.</Message> : loading ? <Message>Loading history…</Message> : error ? <Message>History could not be loaded: {error}</Message> : rows.length ? <div className="platform-object-list">{rows.map(r => <div className="platform-history" key={r.id}><strong>{r.collector} · {r.state}</strong><span>{r.ts} · {r.reason}</span></div>)}</div> : <Message>No health transitions recorded.</Message>}</section>;
}
// What the signed-in role may do, from the platform's own matrix (the platform enforces it too: this only explains).
let sessionCache = { token: null, promise: null };
function usePermissions() {
  const [session, setSession] = useState(null);
  useEffect(() => {
    if (!LIVE) return;
    // One request per sign-in, shared by every button; a different person signing in gets their own answer.
    const token = currentToken();
    if (sessionCache.token !== token) sessionCache = { token, promise: request('/v1/session').catch(() => null) };
    sessionCache.promise.then(setSession);
  }, []);
  const can = (permission) => !LIVE || !session || (session.permissions || []).includes(permission);
  return { role: session?.role, can, why: (permission) => (can(permission) ? undefined : `Your role (${session?.role}) cannot do this. It needs the ${permission} permission.`) };
}

// AI summary: Gemini explains the incident from its metadata only. It is on demand, labelled, and never replaces the
// rule-based recommendation shown with the incident.
function AiSummary({ incidentId }) {
  const [state, setState] = useState({ status: 'idle' });
  const perms = usePermissions();
  useEffect(() => { setState({ status: 'idle' }); }, [incidentId]);
  async function generate() {
    setState({ status: 'loading' });
    try { setState({ status: 'done', result: await request(`/v1/incidents/${encodeURIComponent(incidentId)}/ai-summary`) }); }
    catch (e) { setState({ status: 'done', result: { available: false, reason: e.message } }); }
  }
  const r = state.result;
  return <section className="ai-summary" aria-label="AI summary">
    <h3>AI summary</h3>
    <p className="muted">Gemini reads only this incident's metadata (signal values, method, thresholds), never raw logs.</p>
    <button className="button" type="button" onClick={generate} disabled={state.status === 'loading' || !perms.can('ai.summary')} title={perms.why('ai.summary')}>{state.status === 'loading' ? 'Writing summary…' : r?.available ? 'Regenerate summary' : 'Generate AI summary'}</button>
    {r?.available && <><p className="ai-text">{r.text}</p><p className="muted">{r.basis} Model: {r.model}{r.cached ? ' (saved result)' : ''}.</p></>}
    {r && !r.available && <Message>{r.reason}</Message>}
  </section>;
}
export function IncidentWorkspace({ incidentId, mode }) {
  const perms = usePermissions();
  const [lineage, setLineage] = useState(null), [actions, setActions] = useState([]), [catalog, setCatalog] = useState({}), [error, setError] = useState(''), [selected, setSelected] = useState(null), [type, setType] = useState('restart_service'), [service, setService] = useState(''), [credential, setCredential] = useState(''), [replicas, setReplicas] = useState(2), [busy, setBusy] = useState(false);
  async function load(signal) {
    try { const [l, a] = await Promise.all([request(`/v1/lineage/incident/${encodeURIComponent(incidentId)}`,{signal}), request(`/v1/actions?incident_id=${encodeURIComponent(incidentId)}`,{signal})]); setLineage(l); setActions(a.actions); setCatalog(a.types); setError(''); }
    catch(e) { if(e.name !== 'AbortError') setError(e.message); }
  }
  useEffect(() => { setLineage(null); setActions([]); setSelected(null); setError(''); if(mode !== 'live') return; const ctrl=new AbortController(); load(ctrl.signal); return () => ctrl.abort(); }, [incidentId,mode]);
  async function submit(e) {
    e.preventDefault(); setBusy(true); setError('');
    const params = type === 'isolate_source' ? {source_id:lineage?.source_id} : type === 'rotate_credentials' ? {credential_ref:credential} : type === 'scale_capacity' ? {service, replicas:Number(replicas)} : {service};
    try { await request('/v1/actions/propose',{method:'POST',body:{incident_id:incidentId,action_type:type,parameters:params}}); await load(); }
    catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  async function transition(id, operation) { setBusy(true); setError(''); try { await request(`/v1/actions/${encodeURIComponent(id)}/${operation}`,{method:'POST'}); await load(); } catch(e) { setError(e.message); } finally { setBusy(false); } }
  if(mode !== 'live') return <div className="platform-workspace"><h3>Evidence & simulated actions</h3><Message>Connect the SaaS to inspect actual payload lineage and propose actions.</Message></div>;
  return <div className="platform-workspace"><h3>Evidence & lineage</h3>{error && <Message>{error}</Message>}{!lineage ? <Message>Loading evidence…</Message> : <><p>Raw records remain local. Follow these metadata objects to see the evidence behind this recommendation.</p><div className="platform-links"><button className="button small" onClick={() => setSelected({type:'collector',id:lineage.collector_id})}>Collector · {lineage.collector_id}</button><button className="button small" onClick={() => setSelected({type:'source',id:lineage.source_id})}>Source · {lineage.source_id}</button><button className="button small" onClick={() => setSelected({type:'recommendation',id:incidentId})}>Recommendation</button></div><ExpandableList className="platform-links" noun="payloads" limit={4} items={(lineage.payload_ids || []).map(id => <button className="button small" key={id} onClick={() => setSelected({type:'observation',id})}>Payload · {id}</button>)}/><p className="platform-hint">{lineage.note}</p></>}
    <SignalEvidence lineage={lineage}/><AiSummary incidentId={incidentId}/><ObjectDetails selected={selected} onSelect={setSelected}/><h3>Simulated actions</h3><p>Propose an action for operator review. No infrastructure commands are executed.</p>
    <form onSubmit={submit} className="platform-form"><label>Action type<select value={type} onChange={e => setType(e.target.value)}>{Object.keys(catalog).map(t => <option key={t} value={t}>{labels[t] || t}</option>)}</select></label>
      {['restart_service','scale_capacity'].includes(type) && <label>Service name<input value={service} required maxLength="64" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" onChange={e => setService(e.target.value)} placeholder="api-service"/></label>}
      {type === 'rotate_credentials' && <label>Credential reference<input value={credential} required maxLength="64" pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}" onChange={e => setCredential(e.target.value)} placeholder="service-account"/></label>}
      {type === 'scale_capacity' && <label>Replicas<input type="number" min="1" max="20" required value={replicas} onChange={e => setReplicas(e.target.value)}/></label>}
      {type === 'isolate_source' && <p>Source: {lineage?.source_id || 'loading…'}</p>}
      <button className="button" type="submit" title={perms.why('action.propose')} disabled={!perms.can('action.propose') || busy || !lineage || !Object.keys(catalog).length}>Propose simulation</button></form>
    {actions.length === 0 ? <Message>No actions proposed for this incident.</Message> : actions.map(a => <Action key={a.id} action={a} busy={busy} transition={transition}/>)}
  </div>;
}
function Action({action, busy, transition}) {
  const perms = usePermissions(), locked = !perms.can('action.decide');
  const [details, setDetails] = useState(null), [error, setError] = useState('');
  useEffect(() => { const ctrl=new AbortController(); request(`/v1/actions/${encodeURIComponent(action.id)}`,{signal:ctrl.signal}).then(setDetails).catch(e => { if(e.name!=='AbortError') setError(e.message); }); return () => ctrl.abort(); }, [action.id,action.updated_at]);
  return <article className="platform-action"><strong>{labels[action.action_type] || action.action_type} · {action.status}</strong><p>{action.rollback_plan}</p><div className="platform-links">{action.status === 'proposed' && <><button className="button small" title={perms.why('action.decide')} disabled={busy || locked} onClick={() => transition(action.id,'approve')}>Approve simulation</button><button className="button small" title={perms.why('action.decide')} disabled={busy || locked} onClick={() => transition(action.id,'reject')}>Reject</button></>}{action.status === 'approved' && <button className="button small" title={perms.why('action.decide')} disabled={busy || locked} onClick={() => transition(action.id,'rollback')}>Record rollback</button>}</div>{error && <Message>{error}</Message>}{details && <ol className="platform-audit">{details.audit.map(entry => <li key={entry.id}>{entry.ts} · {entry.action} · {entry.detail.role}</li>)}</ol>}</article>;
}
