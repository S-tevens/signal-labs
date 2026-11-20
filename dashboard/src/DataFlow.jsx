import React, { useEffect, useMemo, useState } from "react";
import { Activity, ArrowRight, Boxes, Cloud, Database, FileJson, Fingerprint, GitBranch, Layers3, LockKeyhole, Minus, Network, Plus, Server, ShieldCheck, ShieldOff, Sparkles, Users, Workflow, Zap } from "lucide-react";
import { request } from "./api";
import { details } from "./FlowDetails.jsx";

const NODE_WIDTH = 150, NODE_HEIGHT = 76, WIDTH = 1470;
const architectureNodes = [
  { id:"infra", x:25,y:80, icon:Server, title:"Infrastructure", subtitle:"CPU · memory · disk", group:"source", description:"Servers and applications produce resource measurements. The collector receives their telemetry inside the customer environment." },
  { id:"network", x:25,y:200, icon:Network, title:"Network", subtitle:"Latency · packet loss", group:"source", description:"Network signals can include latency, bandwidth, connectivity and packet loss. Availability depends on the configured collector sources." },
  { id:"security", x:25,y:320, icon:ShieldCheck, title:"Security events", subtitle:"Authentication signals", group:"source", description:"Authentication events are analyzed locally. The central platform receives approved counts and categories, not raw login records." },
  { id:"apps", x:25,y:440, icon:Layers3, title:"Applications", subtitle:"Service events", group:"source", description:"Applications and services can produce metrics or events for the local collector to process." },
  { id:"collect", x:210,y:260, icon:Activity, title:"Local collector", subtitle:"Collect & normalize", group:"local", description:"The collector reads configured sources and normalizes telemetry within the customer environment.", link:"#/fleet", linkText:"View collectors" },
  { id:"raw", x:395,y:105, icon:LockKeyhole, title:"Raw data store", subtitle:"Stays on premises", group:"private", description:"Raw records and sensitive details remain in the customer environment. Access to the real local store belongs to the collector's local interface.", link:"#/egress", linkText:"View egress example" },
  { id:"redact", x:395,y:260, icon:ShieldOff, title:"Filter & redact", subtitle:"Remove sensitive fields", group:"local", description:"The local pipeline filters records and scrubs sensitive values before constructing metadata. Redaction is a defense in depth; it is not proof that arbitrary free text is safe." },
  { id:"aggregate", x:580,y:260, icon:Boxes, title:"Aggregate", subtitle:"Analyze local windows", group:"local", description:"The collector groups observations into windows and produces derived metrics or event summaries, such as failed-login counts." },
  { id:"policy", x:765,y:260, icon:ShieldCheck, title:"Policy gate", subtitle:"Allow-listed metadata", group:"local", description:"The collector applies the payload schema and customer policy. Only permitted fields are eligible to leave the local environment.", link:"#/egress", linkText:"Inspect outgoing example" },
  { id:"outbox", x:765,y:445, icon:Database, title:"Local outbox", subtitle:"Buffer & retry", group:"local", description:"Approved payloads are queued locally and retried when the SaaS is reachable. Unique IDs let the receiver identify repeated delivery." },
  { id:"ingest", x:950,y:260, icon:Cloud, title:"SaaS ingest", subtitle:"Authenticate & validate", group:"cloud", description:"The SaaS verifies collector credentials and HMAC signatures, validates the frozen metadata contract, and rejects mismatched identities. TLS is required for deployment." },
  { id:"store", x:1135,y:105, icon:Database, title:"Metadata store", subtitle:"Tenant-scoped storage", group:"cloud", description:"The SaaS stores approved metadata with tenant isolation and unique payload IDs. Raw collector records are not part of this central store.", link:"#/objects", linkText:"Explore metadata objects" },
  { id:"aiops", x:1135,y:330, icon:Sparkles, title:"AIOps analysis", subtitle:"Detect & correlate", group:"cloud", description:"The platform compares signals with baselines and correlates related events. Recommendations use heuristic evidence, not a proven root cause." },
  { id:"health", x:1310,y:20, icon:Activity, title:"Health & history", subtitle:"Four health states", group:"output", description:"Collector health and timestamped state changes help operators see availability and degradation.", link:"#/history", linkText:"View health history" },
  { id:"incident", x:1310,y:160, icon:Zap, title:"Incidents", subtitle:"Related signals grouped", group:"output", description:"Related alerts can be grouped into an incident, with metadata signals and payload IDs available for investigation.", link:"#/incidents", linkText:"View incidents" },
  { id:"recommend", x:1310,y:305, icon:Sparkles, title:"Recommendations", subtitle:"Explain the evidence", group:"output", description:"Recommendations describe the contributing signals and suggest an investigation. They are not proof of causation.", link:"#/incidents", linkText:"Inspect incidents" },
];
const architectureEdges = [
  ["infra","collect"],["network","collect"],["security","collect"],["apps","collect"],
  ["collect","raw"],["collect","redact"],["redact","aggregate"],["aggregate","policy"],
  ["policy","outbox","vertical"],["outbox","ingest"],["ingest","store"],["store","aiops","vertical"],
  ["store","health"],["aiops","incident"],["incident","recommend","vertical"],
];

function edgePath(a, b, direction) {
  if (direction === "branch") {
    const x1=a.x+NODE_WIDTH/2, y1=a.y+NODE_HEIGHT, x2=b.x+NODE_WIDTH/2, y2=b.y;
    return `M ${x1} ${y1} C ${x1} 625, ${x2} 625, ${x2} ${y2-3}`;
  }
  if (direction === "vertical") {
    const x1=a.x+NODE_WIDTH/2, y1=a.y+NODE_HEIGHT, x2=b.x+NODE_WIDTH/2, y2=b.y;
    const mid=(y1+y2)/2;
    return `M ${x1} ${y1} C ${x1} ${mid}, ${x2} ${mid}, ${x2} ${y2-3}`;
  }
  const x1=a.x+NODE_WIDTH, y1=a.y+NODE_HEIGHT/2, x2=b.x, y2=b.y+NODE_HEIGHT/2;
  const mid=(x1+x2)/2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2-3} ${y2}`;
}

function Graph({nodes, edges, selected, onSelect, zoom, height=620, architecture=false, expanded=null, active=null}) {
  const byId = Object.fromEntries(nodes.map(n => [n.id,n]));
  return <div className="flow-scroll" role="region" aria-label="Scrollable data flow diagram" tabIndex={0}>
    <div className="flow-sizing" style={{width:WIDTH*zoom,height:height*zoom}}>
      <div className="flow-canvas" style={{width:WIDTH,height,transform:`scale(${zoom})`}}>
        {architecture && <><div className="flow-zone local-zone"/><div className="flow-zone cloud-zone"/></>}
        <svg className="flow-connections" viewBox={`0 0 ${WIDTH} ${height}`} aria-hidden="true"><defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9eabb9"/></marker><marker id="flow-arrow-selected" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#326de3"/></marker></defs>{edges.map(([from,to,direction]) => byId[from] && byId[to] && <path key={`${from}-${to}`} d={edgePath(byId[from],byId[to],direction)} className={selected === from || selected === to ? "is-highlighted" : ""} markerEnd={selected === from || selected === to ? "url(#flow-arrow-selected)" : "url(#flow-arrow)"}/>)}</svg>
        {expanded && <div className="flow-map-explanation" aria-live="polite"><strong>{active?.detail ? active.title : expanded.title}</strong><span>{active?.detail ? active.description : expanded.description}</span></div>}
        {nodes.map(node => <button key={node.id} type="button" className={`flow-node ${node.group || "local"} ${node.detail ? "flow-child-node" : ""} ${selected===node.id ? "selected" : ""}`} style={{left:node.x,top:node.y,width:NODE_WIDTH,height:NODE_HEIGHT}} onClick={() => onSelect(node.id)} aria-pressed={selected === node.id} title={node.fullTitle || node.title}>{!architecture && <span className="flow-node-icon"><node.icon size={17}/></span>}<span className="flow-node-content"><strong>{node.title}</strong><small>{node.subtitle}</small></span></button>)}
      </div>
    </div>
  </div>;
}

function makeLineage(data, incident) {
  const ids = [...new Set(data.payload_ids || [])];
  const visible = ids.slice(0, 8);
  const height = Math.max(620, 135 + visible.length * 90);
  const center = Math.min(height - 140, Math.max(220, 65 + visible.length * 42));
  const nodes = [
    {id:"collector",x:35,y:center,icon:Server,title:"Collector",subtitle:data.collector_id,group:"local",description:`Collector ${data.collector_id} sent the approved metadata associated with this incident.`},
    {id:"source",x:260,y:center,icon:Fingerprint,title:"Source",subtitle:data.source_id,group:"source",description:`Source ${data.source_id} is a pseudonymous identifier. Original source identity remains local.`},
    ...visible.map((id,i)=>({id:`payload-${i}`,x:505,y:65+i*90,icon:FileJson,title:"Metadata payload",subtitle:`${id.slice(0,8)}…`,fullTitle:id,group:"cloud",description:`Payload ID: ${id}. This is a metadata reference; raw records are accessible only through the collector's local interface.`})),
    {id:"incident",x:850,y:center,icon:Zap,title:"Incident",subtitle:`${incident.id.slice(0,8)}…`,fullTitle:incident.id,group:"output",description:incident.description || "Signals associated with this incident are grouped for review.",link:"#/incidents",linkText:"Open incidents"},
    {id:"recommend",x:1080,y:center,icon:Sparkles,title:"Recommendation",subtitle:"Evidence-based guidance",group:"output",description:data.recommendation?.action || "No recommendation is available for this incident.",link:"#/incidents",linkText:"Review recommendation"},
    {id:"actions",x:1310,y:center,icon:Users,title:"Action review",subtitle:"Simulated · operator",group:"output",description:"Any action must be proposed and reviewed in the incident workspace. Actions in this prototype are simulated.",link:"#/incidents",linkText:"View action workspace"},
  ];
  const edges = [["collector","source"], ...visible.flatMap((_,i)=>[["source",`payload-${i}`],[`payload-${i}`,"incident"]]),["incident","recommend"],["recommend","actions"]];
  return {nodes,edges,height,total:ids.length};
}

function LiveTopology({ mode, collectors }) {
  const [status, setStatus] = useState(null), [proxy, setProxy] = useState(null), [error, setError] = useState('');
  useEffect(() => {
    if (mode !== 'live') return;
    let active = true;
    async function load() {
      const [system, balance] = await Promise.allSettled([request('/v1/system/status'), request('/_lb/status')]);
      if (!active) return;
      if (system.status === 'fulfilled') { setStatus(system.value); setError(''); }
      else { setStatus(null); setError(system.reason.message); }
      setProxy(balance.status === 'fulfilled' ? balance.value : null);
    }
    load(); const timer = setInterval(load, 5000);
    return () => { active = false; clearInterval(timer); };
  }, [mode]);
  if (mode !== 'live') return <section className="panel topology"><h2>Live system status</h2><p>Connect the SaaS to see collector, proxy, replica and database status.</p></section>;
  return <section className="panel topology"><div className="topology-heading"><div><span className="flow-kicker">LIVE PLATFORM</span><h2>Delivery at a glance</h2><p>Refreshes every 5 seconds · tenant and region of the connected account</p></div>{status && <span>{status.tenant_id} · {status.region.toUpperCase()}</span>}</div>
    {error && <p role="alert">Platform status unavailable: {error}</p>}
    <div className="topology-grid">
      <div><span>01 / COLLECTORS</span><strong>{status ? `${collectors.filter(c => c.online).length} online in view` : 'Unavailable'}</strong><small>{status ? `${status.collectors} registered in tenant` : 'Waiting for platform'}</small></div>
      <div><span>02 / PROXY</span><strong>{proxy ? 'Reachable' : 'Unavailable'}</strong><small>{proxy ? `${proxy.total_requests ?? 0} requests · ${proxy.failovers ?? 0} failovers` : 'Proxy status endpoint not available'}</small></div>
      <div><span>03 / REPLICAS</span><strong>{proxy?.upstreams ? `${proxy.upstreams.filter(u => u.healthy).length} / ${proxy.upstreams.length} healthy` : status ? `Replica ${status.replica_id} responding` : 'Unavailable'}</strong><small>{proxy?.upstreams ? proxy.upstreams.map((u,i) => `Replica ${i+1}: ${u.healthy ? 'healthy' : 'down'}`).join(' · ') : 'Other replica status unavailable'}</small></div>
      <div><span>04 / DATABASE</span><strong>{status ? 'Reachable' : 'Unavailable'}</strong><small>{status ? `${status.payloads} retained payloads · ${status.incidents} incidents` : 'Waiting for platform'}</small></div>
    </div></section>;
}

export default function DataFlow({ collectors, incidents, region, mode }) {
  const [view,setView]=useState("architecture"), [selected,setSelected]=useState("policy"), [zoom,setZoom]=useState(.8), [incidentId,setIncidentId]=useState(""), [lineage,setLineage]=useState(null), [error,setError]=useState(""), [loading,setLoading]=useState(false);
  const [expandedId,setExpandedId]=useState(null);
  const selectNode = (id) => {
    if (view === "architecture" && !id.startsWith("detail:")) setExpandedId(current => current === id ? null : id);
    setSelected(id);
  };
  const inRegion = useMemo(() => incidents.filter(i => region === "all" || i.region === region),[incidents,region]);
  useEffect(() => { if (!inRegion.some(i => i.id === incidentId)) setIncidentId(inRegion[0]?.id || ""); },[inRegion,incidentId]);
  useEffect(() => {
    if(view !== "lineage" || mode !== "live" || !incidentId) { setLineage(null); setError(""); setLoading(false); return; }
    const ctrl=new AbortController(); setLoading(true); setError(""); setLineage(null);
    request(`/v1/lineage/incident/${encodeURIComponent(incidentId)}`,{signal:ctrl.signal}).then(setLineage).catch(e=>{if(e.name!=="AbortError")setError(e.message);}).finally(()=>{if(!ctrl.signal.aborted)setLoading(false);});
    return ()=>ctrl.abort();
  },[view,mode,incidentId]);
  const activeIncident=inRegion.find(i=>i.id===incidentId);
  const lineageGraph=lineage && activeIncident ? makeLineage(lineage,activeIncident) : null;
  const expanded=architectureNodes.find(n=>n.id===expandedId);
  const detailNodes=expanded ? (details[expanded.id] || []).map(([title,subtitle,description],i)=>({id:`detail:${expanded.id}:${i}`,x:105+i*315,y:700,icon:FileJson,title,subtitle,description,group:expanded.group,detail:true})) : [];
  const graph=view === "architecture" ? {nodes:[...architectureNodes,...detailNodes],edges:[...architectureEdges,...detailNodes.map(n=>[expanded.id,n.id,"branch"])],height:expanded ? 950 : 620} : lineageGraph;
  const active=graph?.nodes.find(n=>n.id===selected);
  const selectView=(v)=>{setView(v);setExpandedId(null);setSelected(v === "architecture" ? "policy" : "incident");};
  return <div className="flow-page">
    <div className="flow-intro"><div><span className="flow-kicker">THE PATH FROM SIGNAL TO INSIGHT</span><h2>Follow the data</h2><p>See how observations become useful insights while sensitive details stay local.</p></div><div className="flow-summary"><span><Server size={15}/><strong>{collectors.length}</strong> {collectors.length === 1 ? "collector" : "collectors"} in view</span><span><Zap size={15}/><strong>{inRegion.length}</strong> {inRegion.length === 1 ? "incident" : "incidents"} in view</span></div></div>
    <LiveTopology mode={mode} collectors={collectors}/>
    <section className="panel flow-panel"><div className="flow-toolbar"><div><span className="flow-kicker">INTERACTIVE MAP</span><h2>{view === "architecture" ? "System data flow" : "Incident lineage"}</h2><p>{view === "architecture" ? "The intended path across the customer and SaaS environments." : "Trace one incident back to its retained metadata evidence."}</p></div><div className="flow-toolbar-actions"><div className="flow-view-switch" aria-label="Flow view"><button type="button" className={view==="architecture"?"active":""} aria-pressed={view==="architecture"} onClick={()=>selectView("architecture")}>Architecture</button><button type="button" className={view==="lineage"?"active":""} aria-pressed={view==="lineage"} onClick={()=>selectView("lineage")}>Incident lineage</button></div><div className="flow-zoom" aria-label="Diagram zoom"><button aria-label="Zoom out" onClick={()=>setZoom(z=>Math.max(.65,Math.round((z-.1)*100)/100))} disabled={zoom<=.65}><Minus size={15}/></button><span>{Math.round(zoom*100)}%</span><button aria-label="Zoom in" onClick={()=>setZoom(z=>Math.min(1.25,Math.round((z+.1)*100)/100))} disabled={zoom>=1.25}><Plus size={15}/></button></div></div></div>
      {view === "lineage" && mode === "live" && <div className="flow-picker"><label htmlFor="flow-incident">Incident</label><select id="flow-incident" value={incidentId} onChange={e=>{setIncidentId(e.target.value);setSelected("incident");}} disabled={!inRegion.length}>{inRegion.length ? inRegion.map(i=><option key={i.id} value={i.id}>{i.title} · {i.id.slice(0,8)}</option>) : <option value="">No incidents in this region</option>}</select><span>Actual metadata links · authenticated SaaS</span></div>}
      {view === "lineage" && mode !== "live" ? <div className="flow-empty"><GitBranch size={27}/><h3>Connect the SaaS to trace an incident</h3><p>Incident lineage needs real payload links from the platform. The architecture map is available in this preview.</p><button className="button" onClick={()=>selectView("architecture")}>View architecture</button></div> : view === "lineage" && !incidentId ? <div className="flow-empty"><GitBranch size={27}/><h3>No incidents to trace</h3><p>Choose a region with an incident, or wait for one to be detected.</p></div> : loading ? <div className="flow-empty"><Activity size={27}/><h3>Loading lineage…</h3></div> : error ? <div className="flow-empty" role="alert"><ShieldOff size={27}/><h3>Lineage could not be loaded</h3><p>{error}</p></div> : graph && <><div className="flow-guide"><span><i/>Select a step to expand its details on the map</span><span>Scroll sideways to see the whole map</span></div><Graph nodes={graph.nodes} edges={graph.edges} selected={selected} onSelect={selectNode} zoom={zoom} height={graph.height} architecture={view === "architecture"} expanded={view === "architecture" ? expanded : null} active={active}/>{lineageGraph && <div className="flow-retention">Showing {Math.min(8,lineageGraph.total)} of {lineageGraph.total} retained payload references. {lineage.note}</div>}</>}
      {active && <div className="flow-inspector" aria-live="polite"><div className={`flow-inspector-icon ${active.group}`}><active.icon size={20}/></div><div className="flow-inspector-copy"><span className="flow-kicker">{active.detail ? "SELECTED DETAIL" : "SELECTED STEP"}</span><h3>{active.title}</h3><p>{active.description}</p></div>{active.link && <a href={active.link} className="flow-inspector-link">{active.linkText} <ArrowRight size={15}/></a>}</div>}
    </section>
    <div className="flow-footer"><span><LockKeyhole size={15}/> Raw records remain inside the customer environment.</span><span><Workflow size={15}/> {view === "architecture" ? "Architecture is a conceptual map, not a live pipeline trace." : "Only retained metadata evidence is shown."}</span></div>
  </div>;
}
