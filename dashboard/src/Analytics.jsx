import React, { useMemo, useState } from "react";
import { Activity, ArrowUpRight, BarChart3, CheckCircle2, Clock3, Cpu, Server, ShieldAlert, Wifi } from "lucide-react";

const STATES = [
  { name: "Excellent", color: "#2662eb" },
  { name: "Good", color: "#86adf8" },
  { name: "Fair", color: "#f38a57" },
  { name: "Poor", color: "#d6dce2" },
];
const SEVERITIES = [
  { name: "Critical", color: "#e95c34" },
  { name: "High", color: "#f39b65" },
  { name: "Medium", color: "#edc493" },
];
const regionLabel = { in: "India", eu: "Europe", all: "All regions" };
const readable = (value, unit = "") => value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(value < 10 ? 1 : 0)}${unit}`;

function Icon({ icon: Glyph, color = "blue" }) {
  return <span className={`analytics-icon ${color}`}><Glyph size={17} /></span>;
}
function CardHeader({ eyebrow, title, action }) {
  return <div className="analytics-card-heading"><div><span className="analytics-eyebrow">{eyebrow}</span><h2>{title}</h2></div>{action}</div>;
}
function Stat({ icon, label, value, detail, tone }) {
  return <article className="analytics-stat"><div className="analytics-stat-top"><span>{label}</span><Icon icon={icon} color={tone} /></div><strong>{value}</strong><small>{detail}</small></article>;
}
function AreaChart({ values, metric }) {
  const clean = values.filter((value) => Number.isFinite(Number(value))).map(Number);
  if (clean.length < 2) return <div className="analytics-chart-empty"><Activity size={22}/><strong>Waiting for readings</strong><span>At least two measurements are needed to draw a trend.</span></div>;
  const max = metric === "cpu" ? Math.max(100, ...clean) : Math.max(10, Math.ceil(Math.max(...clean) / 50) * 50);
  const x = (i) => 15 + (i * 670) / (clean.length - 1);
  const y = (v) => 195 - (Math.max(0, v) / max) * 160;
  const points = clean.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const last = clean.at(-1);
  return <div className="analytics-plot"><div className="analytics-y-axis"><span>{max}{metric === "cpu" ? "%" : " ms"}</span><span>{Math.round(max / 2)}{metric === "cpu" ? "%" : " ms"}</span><span>0</span></div><div className="analytics-plot-body"><svg viewBox="0 0 700 220" preserveAspectRatio="none" role="img" aria-label={`${metric === "cpu" ? "CPU" : "Latency"} trend, latest value ${readable(last, metric === "cpu" ? "%" : " ms")}`}><defs><linearGradient id="analytics-area-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#467bf0" stopOpacity="0.23"/><stop offset="100%" stopColor="#d9e8ff" stopOpacity="0.03"/></linearGradient></defs>{[35,115,195].map(yValue => <line key={yValue} x1="0" x2="700" y1={yValue} y2={yValue} stroke="#e9edf2" strokeDasharray="4 6"/>)}<polygon points={`15,195 ${points} 685,195`} fill="url(#analytics-area-fill)"/><polyline points={points} fill="none" stroke="#2b67e9" strokeWidth="2.75" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round"/><circle cx={x(clean.length-1)} cy={y(last)} r="5" fill="#fff" stroke="#2b67e9" strokeWidth="2" vectorEffect="non-scaling-stroke"/></svg><div className="analytics-x-axis"><span>Earlier readings</span><span>{clean.length} data points</span><span>Latest</span></div></div></div>;
}
function HealthCard({ collectors }) {
  const counts = STATES.map(s => ({ ...s, count: collectors.filter(c => c.state === s.name).length }));
  const unknown = collectors.length - counts.reduce((sum, state) => sum + state.count, 0);
  if (unknown) counts.push({ name: "Unknown", color: "#a8b2bd", count: unknown });
  let start = 0;
  const stops = counts.filter(s => s.count).map(s => { const from = start; start += (s.count / collectors.length) * 100; return `${s.color} ${from}% ${start}%`; });
  return <section className="panel analytics-health"><CardHeader eyebrow="COLLECTOR COMPOSITION" title="Collector health" action={<span className="analytics-pill">{collectors.length} total</span>}/><div className="analytics-health-body"><div className="analytics-donut" style={{background: stops.length ? `conic-gradient(${stops.join(",")})` : "#edf0f4"}} role="img" aria-label={counts.map(s => `${s.name}: ${s.count}`).join(", ")}><div><strong>{String(collectors.length).padStart(2,"0")}</strong><span>collectors</span></div></div><div className="analytics-health-legend">{counts.map(s => <div key={s.name}><span><i style={{background:s.color}}/>{s.name}</span><strong>{String(s.count).padStart(2,"0")}</strong></div>)}</div></div><p className="analytics-card-note">A snapshot of the latest reported health state.</p></section>;
}
function IncidentCard({ incidents }) {
  const counts = SEVERITIES.map(s => ({...s, count:incidents.filter(i => i.severity === s.name).length}));
  const other = incidents.length - counts.reduce((sum,s) => sum+s.count,0);
  const groups = other ? [...counts,{name:"Other", color:"#a8b2bd", count:other}] : counts;
  const alertCount = incidents.reduce((sum,incident) => sum+(Number(incident.count)||0),0);
  return <section className="panel analytics-incidents"><CardHeader eyebrow="EVENT INTELLIGENCE" title="Incident breakdown" action={<a href="#/incidents" className="analytics-text-link">View incidents <ArrowUpRight size={14}/></a>}/><div className="analytics-incident-total"><strong>{String(incidents.length).padStart(2,"0")}</strong><div><span>correlated incidents</span><small>{alertCount} related alerts</small></div></div><div className="analytics-stack" aria-label={`Incident count ${incidents.length}`}>{incidents.length ? groups.filter(s => s.count).map(s => <span key={s.name} style={{flex:s.count,background:s.color}}/>) : <span style={{background:"#edf0f4",flex:1}}/>}</div><div className="analytics-severity">{groups.map(s => <div key={s.name}><span><i style={{background:s.color}}/>{s.name}</span><strong>{s.count}</strong></div>)}</div><p className="analytics-card-note">Related alerts are grouped by source and time.</p></section>;
}
function Signals({ cpu, latency, mode, region }) {
  const [metric, setMetric] = useState("cpu");
  const [range, setRange] = useState(20);
  const all = metric === "cpu" ? cpu : latency;
  const series = all.filter(v => v != null && Number.isFinite(Number(v))).slice(-range).map(Number);
  const unit = metric === "cpu" ? "%" : " ms";
  const max = metric === "cpu" ? Math.max(100, ...series) : Math.max(10, Math.ceil(Math.max(0, ...series) / 50) * 50);
  return <section className="analytics-overview panel">
    <div className="analytics-overview-head"><div><span className="analytics-eyebrow">SIGNAL ACTIVITY</span><h2>Infrastructure overview</h2><p>Latest {metric === "cpu" ? "CPU utilization" : "network latency"} readings for {regionLabel[region]}.</p></div><div className="analytics-controls"><div className="analytics-segmented" aria-label="Metric"><button type="button" aria-pressed={metric === "cpu"} className={metric === "cpu" ? "active" : ""} onClick={() => setMetric("cpu")}>CPU</button><button type="button" aria-pressed={metric === "latency"} className={metric === "latency" ? "active" : ""} onClick={() => setMetric("latency")}>Latency</button></div><select aria-label="Number of readings" value={range} onChange={e => setRange(Number(e.target.value))}><option value="10">Last 10 readings</option><option value="20">Last 20 readings</option><option value="30">Last 30 readings</option></select></div></div>
    <div className="analytics-overview-meta"><div><span>Latest reading</span><strong>{readable(series.at(-1),unit)}</strong></div><div><span>Average of shown</span><strong>{readable(series.length ? series.reduce((a,b)=>a+b,0)/series.length : null,unit)}</strong></div><div><span>Peak of shown</span><strong>{readable(series.length ? Math.max(...series) : null,unit)}</strong></div><div><span>Readings shown</span><strong>{series.length}</strong></div></div>
    {series.length ? <div className="analytics-bars-chart"><div className="analytics-bars-axis"><span>{readable(max,unit)}</span><span>{readable(max/2,unit)}</span><span>0</span></div><div className="analytics-bars-wrap"><div className="analytics-gridlines"><i/><i/><i/></div><div className="analytics-bars" role="img" aria-label={`${metric} trend with ${series.length} readings; latest ${readable(series.at(-1),unit)}`}>{series.map((value,i)=><div key={i} className="analytics-bar-slot"><div className={`analytics-bar ${metric === "latency" ? "latency" : ""}`} style={{height:`${Math.max(2,Math.min(100,value/max*100))}%`}} title={`Reading ${i+1}: ${readable(value,unit)}`}><span>{readable(value,unit)}</span></div></div>)}</div><div className="analytics-bars-labels"><span>Earlier</span><span>{mode === "live" ? "10-second aggregated buckets" : "Sample sequence"}</span><span>Latest</span></div></div></div> : <div className="analytics-chart-empty"><Activity size={22}/><strong>Waiting for readings</strong><span>No {metric} measurements are available for this region.</span></div>}
  </section>;
}
function Busiest({ collectors, onSelectCollector }) {
  const values = collectors.filter(c => c.cpu != null && Number.isFinite(Number(c.cpu))).sort((a,b) => b.cpu - a.cpu).slice(0,4);
  return <section className="panel analytics-load"><CardHeader eyebrow="RESOURCE ACTIVITY" title="Highest CPU usage" action={<a href="#/fleet" className="analytics-text-link">View collectors <ArrowUpRight size={14}/></a>}/><p className="analytics-description">Latest available readings by collector.</p><div className="analytics-load-list">{values.length ? values.map((c,index) => <button className="analytics-load-row" key={c.id} onClick={() => onSelectCollector(c)}><span className="analytics-load-rank">{String(index+1).padStart(2,"0")}</span><span className="analytics-load-main"><strong>{c.name}</strong><span><i style={{width:`${Math.max(0,Math.min(100,c.cpu))}%`,background:c.cpu >= 80 ? "#ef7946" : "#3f73ec"}}/></span></span><b>{readable(c.cpu,"%")}</b></button>) : <div className="analytics-no-data">No current CPU readings available.</div>}</div><p className="analytics-card-note">Offline or missing values are excluded.</p></section>;
}
function MoreAnalytics({ collectors, incidents, latency }) {
  const resource = collectors.filter(c => (c.cpu != null && Number.isFinite(Number(c.cpu))) || (c.memory != null && Number.isFinite(Number(c.memory)))).slice(0,6);
  const points = latency.filter(v => v != null && Number.isFinite(Number(v))).map(Number).slice(-20);
  const max = Math.max(10, ...points);
  const line = points.map((v,i) => `${10 + i*280/Math.max(1,points.length-1)},${95-Math.max(0,v)/max*80}`).join(' ');
  const categories = Object.entries(incidents.reduce((out,i) => { const key=i.category || 'Other'; out[key]=(out[key] || 0)+1; return out; },{})).sort((a,b)=>b[1]-a[1]);
  const colors = ['#6f78e8','#36b9ce','#f4a05e','#e777ae','#82b1ed'];
  return <div className="analytics-extra-grid">
    <section className="panel analytics-extra-card"><div className="analytics-extra-heading"><span className="analytics-extra-icon purple"><Cpu size={15}/></span><div><h2>CPU & memory</h2><p>Latest readings by collector</p></div></div><div className="analytics-extra-legend"><span><i style={{background:'#7182ec'}}/>CPU</span><span><i style={{background:'#43bdd0'}}/>Memory</span></div>{resource.length ? <div className="resource-comparison" role="img" aria-label={resource.map(c=>`${c.name}: CPU ${readable(c.cpu,'%')}, memory ${readable(c.memory,'%')}`).join('; ')}>{resource.map(c=><div className="resource-column" key={c.id} title={`${c.name}: CPU ${readable(c.cpu,'%')}, memory ${readable(c.memory,'%')}`}><div className="resource-pair"><i style={{height:`${Math.min(100,Math.max(0,Number(c.cpu)||0))}%`,background:'#7182ec'}}/><i style={{height:`${Math.min(100,Math.max(0,Number(c.memory)||0))}%`,background:'#43bdd0'}}/></div><span>{c.name}</span></div>)}</div> : <div className="extra-empty">No CPU or memory readings available.</div>}<p className="analytics-extra-foot">Percentage · missing readings are not shown</p></section>
    <section className="panel analytics-extra-card"><div className="analytics-extra-heading"><span className="analytics-extra-icon cyan"><Wifi size={15}/></span><div><h2>Latency trend</h2><p>Latest available readings</p></div></div><div className="latency-summary"><strong>{readable(points.at(-1),' ms')}</strong><span>{points.length ? `${points.length} readings` : 'No readings'}</span></div>{points.length >= 2 ? <svg className="latency-spark" viewBox="0 0 300 110" preserveAspectRatio="none" role="img" aria-label={`Latency trend: ${points.length} readings, latest ${readable(points.at(-1),' ms')}`}><line x1="10" x2="290" y1="15" y2="15"/><line x1="10" x2="290" y1="55" y2="55"/><line x1="10" x2="290" y1="95" y2="95"/><polyline points={line}/><circle cx="290" cy={95-Math.max(0,points.at(-1))/max*80} r="4"/></svg> : <div className="extra-empty">At least two readings are needed to show a trend.</div>}<div className="spark-labels"><span>Earlier</span><span>Latest</span></div><p className="analytics-extra-foot">Network latency · milliseconds</p></section>
    <section className="panel analytics-extra-card"><div className="analytics-extra-heading"><span className="analytics-extra-icon coral"><Activity size={15}/></span><div><h2>Incident categories</h2><p>Breakdown of current incidents</p></div></div><div className="category-total"><strong>{incidents.length}</strong><span>incidents</span></div>{categories.length ? <><div className="category-stack" role="img" aria-label={categories.map(([name,n])=>`${name}: ${n}`).join(', ')}>{categories.map(([name,n],i)=><span key={name} style={{flex:n,background:colors[i%colors.length]}} title={`${name}: ${n}`}/>)}</div><div className="category-list">{categories.map(([name,n],i)=><div key={name}><span><i style={{background:colors[i%colors.length]}}/>{name}</span><strong>{n}</strong></div>)}</div></> : <div className="extra-empty">No incidents in this region.</div>}<p className="analytics-extra-foot">Grouped by incident category</p></section>
  </div>;
}
function Delivery({ proof, mode }) {
  const data = mode === "demo" ? {p95_dashboard_latency_s:2.4,max_alert_delay_s:4.8,offline_detection_s:52} : proof;
  const metrics = [{label:"Dashboard p95",value:data?.p95_dashboard_latency_s,target:"Target ≤ 10s"},{label:"Slowest alert",value:data?.max_alert_delay_s,target:"Target ≤ 15s"},{label:"Offline detection",value:data?.offline_detection_s,target:"Target ≤ 60s"}];
  return <section className="panel analytics-delivery"><CardHeader eyebrow="PERFORMANCE" title="Delivery at a glance" action={<a href="#/proof" className="analytics-text-link">View proof <ArrowUpRight size={14}/></a>}/><div className="analytics-delivery-items">{metrics.map(m => <div key={m.label}><span>{m.label}</span><strong>{readable(m.value,"s")}</strong><small>{m.target}</small></div>)}</div><div className="analytics-delivery-note"><Clock3 size={15}/><span>{mode === "demo" ? "Illustrative measurements · all regions" : "Recent five-minute window · entire tenant"}</span></div></section>;
}
export default function Analytics({ collectors, incidents, region, mode, proof, cpuSeries, latencySeries, analyticsSeries, onSelectCollector }) {
  const online = collectors.filter(c => c.online ?? (typeof c.seen === "number" && c.seen < 60)).length;
  const needsAttention = collectors.filter(c => c.state === "Fair" || c.state === "Poor").length;
  const avg = key => { const v=collectors.map(c=>c[key]).filter(n=>n != null && Number.isFinite(Number(n))).map(Number); return v.length ? v.reduce((a,b)=>a+b,0)/v.length : null; };
  const series = useMemo(() => mode === "live" ? (analyticsSeries?.[region] ?? {cpu:[],latency:[]}) : region === "eu" ? {cpu:[],latency:[]} : {cpu:cpuSeries,latency:latencySeries}, [mode,analyticsSeries,region,cpuSeries,latencySeries]);
  const stats = [
    { label:"Collectors", value:collectors.length, detail:`${online} reporting`, color:"#339fec" },
    { label:"Needs attention", value:needsAttention, detail:"Fair or Poor health", color:"#ef9b54" },
    { label:"Incidents", value:incidents.length, detail:`${incidents.reduce((sum,i)=>sum+(Number(i.count)||0),0)} related alerts`, color:"#ed79b9" },
    { label:"Average CPU", value:readable(avg("cpu"),"%"), detail:"Across reporting collectors", color:"#8d88ee" },
    { label:"Average latency", value:readable(avg("latency")," ms"), detail:"Across reporting collectors", color:"#3bbf9a" },
  ];
  function exportSnapshot() {
    const rows=[["collector","region","health","online","cpu_pct","memory_pct","latency_ms","packet_loss_pct"],...collectors.map(c=>[c.name,c.region,c.state,c.online ?? "",c.cpu ?? "",c.memory ?? "",c.latency ?? "",c.loss ?? ""])];
    const csv=rows.map(row=>row.map(value=>`"${String(value ?? "").replaceAll('"','""')}"`).join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})); const link=document.createElement("a"); link.href=url; link.download="signal-labs-collector-snapshot.csv"; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <div className="analytics-page analytics-detailed">
    <div className="analytics-page-intro"><div><span className="analytics-eyebrow">OBSERVABILITY / {regionLabel[region].toUpperCase()}</span><h2>Analytics overview</h2><p>Monitor collector health, infrastructure activity, and incidents in one place.</p></div><div className="analytics-intro-actions"><span className="analytics-source"><i/>{mode === "live" ? "Live data" : "Sample data"}</span><button type="button" className="analytics-export" onClick={exportSnapshot}>↓ &nbsp; Export snapshot</button></div></div>
    <div className="analytics-kpi-strip">{stats.map(s=><article className="analytics-kpi" key={s.label}><span><i style={{background:s.color}}/>{s.label}</span><strong>{s.value}</strong><small>{s.detail}</small></article>)}</div>
    <Signals cpu={series.cpu} latency={series.latency} mode={mode} region={region}/>
    <div className="analytics-section-title"><div><span className="analytics-eyebrow">A CLOSER LOOK</span><h2>Collector & incident insights</h2></div><span>Current snapshot · {regionLabel[region]}</span></div>
    <div className="analytics-detail-grid"><Busiest collectors={collectors} onSelectCollector={onSelectCollector}/><HealthCard collectors={collectors}/><IncidentCard incidents={incidents}/></div>
    <MoreAnalytics collectors={collectors} incidents={incidents} latency={series.latency}/>
    <Delivery proof={proof} mode={mode}/><div className="analytics-bottom"><span><CheckCircle2 size={15}/>Collector data is shown for {regionLabel[region].toLowerCase()}.</span><span><BarChart3 size={15}/>Insights from approved metadata.</span></div>
  </div>;
}
