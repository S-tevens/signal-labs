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
  return <section className="panel analytics-health"><CardHeader eyebrow="FLEET COMPOSITION" title="Collector health" action={<span className="analytics-pill">{collectors.length} total</span>}/><div className="analytics-health-body"><div className="analytics-donut" style={{background: stops.length ? `conic-gradient(${stops.join(",")})` : "#edf0f4"}} role="img" aria-label={counts.map(s => `${s.name}: ${s.count}`).join(", ")}><div><strong>{String(collectors.length).padStart(2,"0")}</strong><span>collectors</span></div></div><div className="analytics-health-legend">{counts.map(s => <div key={s.name}><span><i style={{background:s.color}}/>{s.name}</span><strong>{String(s.count).padStart(2,"0")}</strong></div>)}</div></div><p className="analytics-card-note">A snapshot of the latest reported health state.</p></section>;
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
  const series = metric === "cpu" ? cpu : latency;
  const latest = series.length ? series.at(-1) : null;
  return <section className="panel analytics-signals"><CardHeader eyebrow="METRIC TRENDS" title="Infrastructure signals" action={<div className="analytics-segmented"><button type="button" aria-pressed={metric === "cpu"} className={metric === "cpu" ? "active" : ""} onClick={() => setMetric("cpu")}>CPU</button><button type="button" aria-pressed={metric === "latency"} className={metric === "latency" ? "active" : ""} onClick={() => setMetric("latency")}>Latency</button></div>}/><div className="analytics-signal-intro"><div><span>{metric === "cpu" ? "CPU utilization" : "Network latency"}</span><strong>{readable(latest, metric === "cpu" ? "%" : " ms")}</strong></div><div className="analytics-signal-caption"><i/>{mode === "demo" ? (region === "eu" ? "No European sample" : "Sample · API cluster") : `${regionLabel[region]} · aggregated readings`}</div></div><AreaChart values={series} metric={metric}/><div className="analytics-chart-foot"><span><i/>Observed signal</span><span>{mode === "demo" ? "Illustrative sample sequence" : "Latest available 10-second buckets · up to 30 min"}</span></div></section>;
}
function Busiest({ collectors, onSelectCollector }) {
  const values = collectors.filter(c => c.cpu != null && Number.isFinite(Number(c.cpu))).sort((a,b) => b.cpu - a.cpu).slice(0,4);
  return <section className="panel analytics-load"><CardHeader eyebrow="RESOURCE ACTIVITY" title="Highest CPU usage" action={<a href="#/fleet" className="analytics-text-link">View fleet <ArrowUpRight size={14}/></a>}/><p className="analytics-description">Latest available readings by collector.</p><div className="analytics-load-list">{values.length ? values.map((c,index) => <button className="analytics-load-row" key={c.id} onClick={() => onSelectCollector(c)}><span className="analytics-load-rank">{String(index+1).padStart(2,"0")}</span><span className="analytics-load-main"><strong>{c.name}</strong><span><i style={{width:`${Math.max(0,Math.min(100,c.cpu))}%`,background:c.cpu >= 80 ? "#ef7946" : "#3f73ec"}}/></span></span><b>{readable(c.cpu,"%")}</b></button>) : <div className="analytics-no-data">No current CPU readings available.</div>}</div><p className="analytics-card-note">Offline or missing values are excluded.</p></section>;
}
function Delivery({ proof, mode }) {
  const data = mode === "demo" ? {p95_dashboard_latency_s:2.4,max_alert_delay_s:4.8,offline_detection_s:52} : proof;
  const metrics = [{label:"Dashboard p95",value:data?.p95_dashboard_latency_s,target:"Target ≤ 10s"},{label:"Slowest alert",value:data?.max_alert_delay_s,target:"Target ≤ 15s"},{label:"Offline detection",value:data?.offline_detection_s,target:"Target ≤ 60s"}];
  return <section className="panel analytics-delivery"><CardHeader eyebrow="PERFORMANCE" title="Delivery at a glance" action={<a href="#/proof" className="analytics-text-link">View proof <ArrowUpRight size={14}/></a>}/><div className="analytics-delivery-items">{metrics.map(m => <div key={m.label}><span>{m.label}</span><strong>{readable(m.value,"s")}</strong><small>{m.target}</small></div>)}</div><div className="analytics-delivery-note"><Clock3 size={15}/><span>{mode === "demo" ? "Illustrative measurements · all regions" : "Recent five-minute window · entire tenant"}</span></div></section>;
}
export default function Analytics({ collectors, incidents, region, mode, proof, cpuSeries, latencySeries, analyticsSeries, onSelectCollector }) {
  const online = collectors.filter(c => c.online ?? (typeof c.seen === "number" && c.seen < 60)).length;
  const needsAttention = collectors.filter(c => c.state === "Fair" || c.state === "Poor").length;
  const cpuValues = collectors.map(c => c.cpu).filter(n => n != null && Number.isFinite(Number(n))).map(Number);
  const avgCpu = cpuValues.length ? cpuValues.reduce((a,b) => a+b,0)/cpuValues.length : null;
  const series = useMemo(() => mode === "live" ? (analyticsSeries?.[region] ?? {cpu:[],latency:[]}) : region === "eu" ? {cpu:[],latency:[]} : {cpu:cpuSeries,latency:latencySeries}, [mode,analyticsSeries,region,cpuSeries,latencySeries]);
  return <div className="analytics-page"><div className="analytics-subheading"><div><span className="analytics-eyebrow">OVERVIEW / {regionLabel[region].toUpperCase()}</span><p>A clearer picture of the signals that matter.</p></div><span className="analytics-source"><i/>{mode === "live" ? "Live data" : "Sample data"}</span></div><div className="analytics-stats-grid"><Stat icon={Server} label="Monitored collectors" value={String(collectors.length).padStart(2,"0")} detail={`${online} reporting in ${regionLabel[region]}`}/><Stat icon={ShieldAlert} label="Needs attention" value={String(needsAttention).padStart(2,"0")} detail="Fair or Poor health state" tone="orange"/><Stat icon={Activity} label="Correlated incidents" value={String(incidents.length).padStart(2,"0")} detail={`${incidents.reduce((sum,i) => sum+(Number(i.count)||0),0)} related alerts`} tone="orange"/><Stat icon={Cpu} label="Average CPU" value={readable(avgCpu,"%")} detail={`${cpuValues.length} ${cpuValues.length === 1 ? "collector" : "collectors"} with readings`}/></div><div className="analytics-main-grid"><Signals cpu={series.cpu} latency={series.latency} mode={mode} region={region}/><HealthCard collectors={collectors}/><IncidentCard incidents={incidents}/><Busiest collectors={collectors} onSelectCollector={onSelectCollector}/></div><Delivery proof={proof} mode={mode}/><div className="analytics-bottom"><span><CheckCircle2 size={15}/>Collector data is shown for {regionLabel[region].toLowerCase()}.</span><span><BarChart3 size={15}/>Insights from approved metadata.</span></div></div>;
}
