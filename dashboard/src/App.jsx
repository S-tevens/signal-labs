import React, { useEffect, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Bell,
  BarChart3,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  Database,
  Download,
  FileJson,
  Globe2,
  GitBranch,
  Layers3,
  ListFilter,
  LockKeyhole,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  ShieldX,
  Sparkles,
  Terminal,
  WifiOff,
  X,
} from "lucide-react";
import {
  collectors as demoCollectors,
  incidents as demoIncidents,
  cpuSeries as demoCpu,
  latencySeries as demoLatency,
  egress,
} from "./data.js";
import { LIVE, useLiveData } from "./api.js";
import Analytics from "./Analytics.jsx";
import DataFlow from "./DataFlow.jsx";
import UsersAdmin from "./Users.jsx";
import { UserMenu } from "./Auth.jsx";
import { ObjectExplorer, HealthHistory, IncidentWorkspace, ReceivedPayload } from "./Platform.jsx";

// Live data from the SaaS when a dashboard token is configured, labelled demo data otherwise.
const DataContext = React.createContext(null);
const useData = () => React.useContext(DataContext);

const pages = {
  fleet: [
    "Overview",
    "",
  ],
  flow: ["Data flow", "Trace the journey from local telemetry to operational insights."],
  analytics: ["Analytics overview", "Understand your collectors, signals, and incidents at a glance."],
  incidents: [
    "Incidents",
    "Less noise. More context. Know what to investigate next.",
  ],
  proof: [
    "Performance proof",
    "Delivery evidence, measured against your hackathon targets.",
  ],
  received: ["Received payload", "Inspect metadata stored for your tenant."],
  objects: ["Object explorer", "Explore linked metadata across your monitored environment."],
  history: ["Health history", "Review collector health changes and their recorded reasons."],
  users: ["Users and roles", "Decide who can see and do what in your organization."],
  egress: [
    "Egress proof",
    "Inspect the boundary between private records and approved metadata.",
  ],
};
const nav = [
  { id: "fleet", label: "Overview", icon: Layers3 },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "flow", label: "Data flow", icon: GitBranch },
  { id: "incidents", label: "Incidents", icon: Activity },
  { id: "proof", label: "Performance proof", icon: ShieldCheck },
  { id: "received", label: "Received payload", icon: FileJson },
  { id: "objects", label: "Object explorer", icon: Database },
  { id: "history", label: "Health history", icon: Clock3 },
  { id: "egress", label: "Local egress", icon: FileJson },
  { id: "users", label: "Users", icon: ShieldCheck, adminOnly: true },
];
const regionName = { in: "India", eu: "Europe" };
function currentPage() {
  const page = location.hash.replace("#/", "").split("?")[0];
  return pages[page] ? page : "fleet";
}
function Badge({ state }) {
  return (
    <span className={`badge ${state.toLowerCase()}`}>
      <span />
      {state}
    </span>
  );
}
function IconBox({ icon: Icon, tone = "" }) {
  return (
    <span className={`icon-box ${tone}`}>
      <Icon size={18} />
    </span>
  );
}
function PanelTitle({ icon: Icon, title, children }) {
  return (
    <div className="panel-title">
      <h2>
        {Icon && <Icon size={17} />}
        {title}
      </h2>
      {children}
    </div>
  );
}
function Empty({ text }) {
  return (
    <div className="empty">
      <Search size={24} />
      <p>{text}</p>
    </div>
  );
}
function downloadJSON(name, data) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Trend({ metric, range, healthy = false }) {
  const { cpuSeries, latencySeries, mode } = useData();
  const series = mode === "demo" && healthy
    ? Array.from(
        { length: 29 },
        (_, i) =>
          (metric === "cpu" ? 38 : 28) +
          Math.sin(i * 0.9) * 4 * (i === 28 ? 0 : 1),
      )
    : metric === "cpu"
      ? cpuSeries
      : latencySeries;
    const values = series.slice(range === "15m" ? -15 : 0);
  if (values.length < 2)
    return (
      <div className="trend">
        <Empty text="Waiting for telemetry…" />
      </div>
    );
  const y = (value) => 180 - (value / (metric === "cpu" ? 100 : 200)) * 160;
  const points = values
    .map((v, i) => `${(i * 800) / (values.length - 1)},${y(v)}`)
    .join(" ");
  const baseline = metric === "cpu" ? 36 : 30;
  return (
    <div className="trend">
      <div className="chart-scale">
        <span>{metric === "cpu" ? "100%" : "200 ms"}</span>
        <span>{metric === "cpu" ? "75%" : "150 ms"}</span>
        <span>{metric === "cpu" ? "50%" : "100 ms"}</span>
        <span>{metric === "cpu" ? "25%" : "50 ms"}</span>
        <span>0</span>
      </div>
      <div className="chart-area">
        <svg
          viewBox="0 0 800 190"
          preserveAspectRatio="none"
          role="img"
          aria-label={`${metric === "cpu" ? "CPU utilization" : "Latency"}  ${mode === "live" ? "live" : "demo"} trend${healthy ? " within baseline" : " with an increase near the end"}`}
        >
          <defs>
            <linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#386feb" stopOpacity=".2" />
              <stop offset="100%" stopColor="#386feb" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[20, 60, 100, 140, 180].map((y) => (
            <line
              key={y}
              x1="0"
              x2="800"
              y1={y}
              y2={y}
              stroke="#e4e8ee"
              strokeDasharray="3 5"
            />
          ))}
          <rect
            x="0"
            y={y(metric === "cpu" ? 45 : 40)}
            width="800"
            height={metric === "cpu" ? 27 : 16}
            fill="#91aadb"
            opacity=".06"
          />
          <line
            x1="0"
            x2="800"
            y1={y(baseline)}
            y2={y(baseline)}
            stroke="#a8b3bf"
            strokeDasharray="5 5"
          />
          <polygon points={`0,190 ${points} 800,190`} fill="url(#chart-fill)" />
          <polyline
            points={points}
            fill="none"
            stroke="#386feb"
            strokeWidth="2.5"
            vectorEffect="non-scaling-stroke"
          />
          <circle cx="800" cy={y(values.at(-1))} r="4" fill="#386feb" />
          {!healthy && (
            <line
              x1="590"
              x2="590"
              y1="10"
              y2="180"
              stroke="#f17946"
              strokeDasharray="4 5"
            />
          )}
        </svg>
        <div className="chart-times">
          {(range === "15m"
            ? ["14:15", "14:18", "14:21", "14:24", "14:27", "14:30"]
            : ["13:30", "13:42", "13:54", "14:06", "14:18", "14:30"]
          ).map((t) => (
            <span key={t}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Fleet({ rows, onSelect, onIncident, range }) {
  const { incidents, cpuSeries, latencySeries, mode, proof } = useData();
  const [metric, setMetric] = useState("cpu");
  const [search, setSearch] = useState("");
  const [state, setState] = useState("all");
  const filtered = rows.filter(
    (c) =>
      (state === "all" || c.state === state) &&
      `${c.name} ${c.id}`.toLowerCase().includes(search.toLowerCase()),
  );
  // Live rows carry the SaaS's own online flag: a collector can be Poor (a critical signal) and still be reporting.
  const online = rows.filter((c) => c.online ?? c.state !== "Poor").length;
    const activeIncidents = incidents.filter((i) =>
    rows.some((c) => c.id === i.collector),
  );
  const healthy =
    mode === "demo"
      ? !rows.some((c) => c.id === "col-blr-02")
      : activeIncidents.length === 0;
  const seriesNow = metric === "cpu" ? cpuSeries : latencySeries;
  const latest = seriesNow.length ? seriesNow[seriesNow.length - 1] : null;
  return (
    <>
      <div className="fleet-hero-grid">
        <section className="panel fleet-status-hero" aria-label="Collector health summary">
          <div className="hero-card-heading"><div><span className="card-kicker">Your infrastructure</span><h2>Collector status</h2></div><span className="light-pill">{rows.length} collectors</span></div>
          <StatusWheel counts={Object.fromEntries(["Excellent", "Good", "Fair", "Poor"].map((state) => [state, rows.filter((c) => c.state === state).length]))} total={rows.length} />
          <div className="hero-total">{String(rows.length).padStart(2, "0")}</div>
          <p className="hero-caption">Monitored collectors in {rows.some(c => c.region === 'eu') && rows.some(c => c.region === 'in') ? 'all demo regions' : rows[0]?.region === 'eu' ? 'Europe' : 'India'} · {online} reporting</p>
        </section>
        <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-top">
            <span>Collectors online</span>
            <Server size={17} />
          </div>
          <div className="stat-value">
            {online}
            <span>/ {rows.length}</span>
          </div>
          <div className="stat-foot">
            <span className="tiny-dot green" />
            {rows.length - online} collector
            {rows.length - online === 1 ? "" : "s"} unreachable
          </div>
          <div className="mini-bars">
            {rows.map((c) => (
              <span key={c.id} className={c.state.toLowerCase()} />
            ))}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Open incidents</span>
            <Activity size={17} />
          </div>
          <div className="stat-value">
            {activeIncidents.length}
            <span className="stat-chip amber">Needs attention</span>
          </div>
          <div className="stat-foot">
            {activeIncidents.reduce((a, i) => a + i.count, 0)} related alerts,
            grouped into incidents
          </div>
          <div className="stat-line amber-line" />
        </div>
        <div className="stat-card">
          <div className="stat-top">
            <span>Dashboard latency · p95</span>
            <Clock3 size={17} />
          </div>
          <div className="stat-value">
            {mode === "live"
              ? proof?.p95_dashboard_latency_s == null
                ? "—"
                : proof.p95_dashboard_latency_s.toFixed(1)
              : "2.4"}
            <span>s</span>
            {(mode === "demo" ||
              (proof?.p95_dashboard_latency_s != null &&
                proof.p95_dashboard_latency_s <= 10)) && (
              <span className="stat-chip">Within target</span>
            )}
          </div>
          <div className="stat-foot">
            Target ≤ 10 seconds{" "}
            <span className="muted">
              {mode === "live"
                ? "· measured from render acknowledgements"
                : "· demo measurement"}
            </span>
          </div>
          <div className="stat-line" />
        </div>
        <div className="stat-card privacy-stat">
          <div className="stat-top">
            <span>Raw data exported</span>
            <LockKeyhole size={17} />
          </div>
          <div className="stat-value">
            0<span>bytes</span>
            <ShieldCheck className="privacy-shield" size={33} />
          </div>
          <div className="stat-foot">
            Approved metadata only{" "}
            <span className="muted">
              {mode === "live" ? "· enforced by schema, not measured" : "· demo"}
            </span>
          </div>
          <div className="stat-line" />
        </div>
      </div>
      </div>
      <div className="overview-grid">
        <section className="panel health-panel">
          <PanelTitle icon={Activity} title="Infrastructure signals">
            <span className="small-tag">
              {mode === "live"
                ? "Live · all collectors"
                : `Demo · ${healthy ? "EU production" : "API cluster"}`}
            </span>
          </PanelTitle>
          <div className="chart-heading">
            <div>
              <div className="segmented">
                <button
                  aria-pressed={metric === "cpu"}
                  className={metric === "cpu" ? "selected" : ""}
                  onClick={() => setMetric("cpu")}
                >
                  CPU utilization
                </button>
                <button
                  aria-pressed={metric === "latency"}
                  className={metric === "latency" ? "selected" : ""}
                  onClick={() => setMetric("latency")}
                >
                  Latency
                </button>
              </div>
              <div className="chart-number">
                {mode === "live"
                  ? latest == null
                    ? "—"
                    : Math.round(latest)
                  : metric === "cpu"
                    ? healthy
                      ? "38"
                      : "91"
                    : healthy
                      ? "28"
                      : "186"}
                <span>{metric === "cpu" ? "%" : "ms"}</span>
                <span className="delta">
                  <ArrowUpRight size={14} />
                  {mode === "live"
                    ? latest == null
                      ? "No data yet"
                      : `Latest of ${seriesNow.length} samples`
                    : healthy
                      ? "Within expected baseline"
                      : metric === "cpu"
                        ? "46 pts above baseline"
                        : "146 ms above baseline"}
                </span>
              </div>
            </div>
            <span className="chart-window">
              {range === "15m" ? "Last 15 minutes" : "Last hour"} · IST
            </span>
          </div>
          <Trend metric={metric} range={range} healthy={healthy} />
          <div className="chart-legend">
            <span>
              <i className="line-key" />
              Observed
            </span>
            <span>
              <i className="line-key dashed" />
              Expected baseline
            </span>
            {!healthy && (
              <span className="anomaly-key">
                <i />
                Anomaly detected
              </span>
            )}
          </div>
        </section>
        <section className="panel health-summary">
          <PanelTitle title="Collector health">
            <span className="small-tag">{rows.length} collectors</span>
          </PanelTitle>
          <div className="health-track">
            {["Excellent", "Good", "Fair", "Poor"].map((s) => (
              <span
                key={s}
                className={s.toLowerCase()}
                style={{
                  flex: rows.filter((c) => c.state === s).length || 0.06,
                }}
              />
            ))}
          </div>
          <div className="health-list">
            {["Excellent", "Good", "Fair", "Poor"].map((s) => (
              <div key={s}>
                <span>
                  <i className={`tiny-dot ${s.toLowerCase()}`} />
                  {s}
                </span>
                <strong>
                  {String(rows.filter((c) => c.state === s).length).padStart(
                    2,
                    "0",
                  )}
                </strong>
              </div>
            ))}
          </div>
          <div className="summary-note">
            <ShieldCheck size={16} />
            <p>
              Your data stays yours.
              <br />
              <span>Raw records remain on the collector.</span>
            </p>
          </div>
        </section>
      </div>
      <section className="panel fleet-panel">
        <PanelTitle icon={Server} title="Collectors">
          <span className="small-tag">
            {filtered.length} of {rows.length} collectors
          </span>
        </PanelTitle>
        <div className="table-toolbar">
          <label className="search-field">
            <Search size={16} />
            <input
              aria-label="Search collectors"
              placeholder="Search collectors…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <kbd>/</kbd>
          </label>
          <label className="select-wrap">
            <ListFilter size={15} />
            <select
              aria-label="Filter by health"
              value={state}
              onChange={(e) => setState(e.target.value)}
            >
              <option value="all">All health states</option>
              {["Excellent", "Good", "Fair", "Poor"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <ChevronDown size={13} />
          </label>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Collector</th>
                <th>Health</th>
                <th>CPU</th>
                <th>Memory</th>
                <th>Latency</th>
                <th>Last seen</th>
                <th aria-label="View details" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((c) => (
                <tr key={c.id} onClick={() => onSelect(c)} className={c.online === false ? "row-offline" : undefined}>
                  <td>
                    <button
                      className="collector-name"
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelect(c);
                      }}
                    >
                      <span
                        className={`server-icon ${c.state === "Poor" ? "offline" : ""}`}
                      >
                        <Server size={17} />
                      </span>
                      <span>
                        <strong>{c.name}</strong>
                        <small>
                          {c.id} <span>· {regionName[c.region]}</span>
                        </small>
                        <small title="The collector process's own load and a fingerprint of its settings">
                          {resourceText(c.resources || {})} · config {c.configHash}
                        </small>
                      </span>
                    </button>
                  </td>
                  <td>
                    <Badge state={c.state} />
                  </td>
                  <td>
                    <div className="metric-cell">
                      {c.cpu == null ? "—" : `${c.cpu}%`}
                      {c.cpu != null && (
                        <span className="meter">
                          <i
                            className={c.cpu > 80 ? "warm" : ""}
                            style={{ width: `${c.cpu}%` }}
                          />
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="mono">
                    {c.memory == null ? "—" : `${c.memory}%`}
                  </td>
                  <td className={`mono ${c.latency > 100 ? "text-amber" : ""}`}>
                    {c.latency == null ? "—" : `${c.latency} ms`}
                  </td>
                  <td>
                    <span className={presence(c).cls}>
                      {presence(c).label} · {ago(c.seen)}
                    </span>
                  </td>
                  <td>
                    <ChevronRight size={16} className="muted" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!filtered.length && (
          <Empty text="No collectors match these filters." />
        )}
        <div className="table-footer">
          <span>
            <LockKeyhole size={13} />
            Pseudonymous sources · Tenant-isolated view
          </span>
          <span>Click a collector to inspect signals</span>
        </div>
      </section>
      <section className="panel incident-preview">
        <PanelTitle icon={Sparkles} title="What needs your attention">
          <a href="#/incidents">
            View incidents <ChevronRight size={14} />
          </a>
        </PanelTitle>
        {!activeIncidents.length && (
          <div className="empty">
            <ShieldCheck size={24} />
            <p>
              No open incidents
              {mode === "live" ? "." : " in this demo region."}
            </p>
          </div>
        )}
        {activeIncidents.slice(0, 2).map((i) => (
          <button
            key={i.id}
            className="incident-row"
            onClick={() => onIncident(i)}
          >
            <IconBox
              icon={i.severity === "Critical" ? WifiOff : Activity}
              tone={i.severity === "Critical" ? "red" : "amber"}
            />
            <div>
              <strong>{i.title}</strong>
              <span>
                {i.collector} <b>·</b> {i.count} related alert
                {i.count > 1 ? "s" : ""}
              </span>
            </div>
            <Badge state={i.severity} />
            <span className="incident-time">{i.time}</span>
            <ChevronRight size={16} />
          </button>
        ))}
      </section>
    </>
  );
}

function Incidents({ region, onSelect }) {
  const { incidents, mode } = useData();
  const [filter, setFilter] = useState("all");
  const list = incidents.filter(
    (i) =>
      (region === "all" || i.region === region) &&
      (filter === "all" || i.severity === filter),
  );
  return (
    <>
      <div className="insight-banner">
        <IconBox icon={Sparkles} />
        <div>
          <strong>One incident. The whole story.</strong>
          <p>
            Related signals are grouped by source and time. Recommendations show
            the evidence behind them.
          </p>
        </div>
        <span className="small-tag">
          {mode === "live" ? "Live correlation" : "Demo correlation"}
        </span>
      </div>
      <div className="section-heading">
        <h2>
          Open incidents <span>{list.length}</span>
        </h2>
        <label className="select-wrap">
          <ListFilter size={15} />
          <select
            aria-label="Incident severity"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All severities</option>
            {["Critical", "High", "Medium"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <ChevronDown size={13} />
        </label>
      </div>
      <div className="incident-cards">
        {list.map((i) => (
          <button
            key={i.id}
            className="incident-card panel"
            onClick={() => onSelect(i)}
          >
            <div className="incident-card-head">
              <span className="mono muted">
                {i.id} <span>· {i.category}</span>
              </span>
              <Badge state={i.severity} />
            </div>
            <h2>{i.title}</h2>
            <p>{i.description}</p>
            <div className="signal-pills">
              {i.signals.slice(0, 2).map((s) => (
                <span key={s.name}>
                  {s.name} <strong>{s.value}</strong>
                </span>
              ))}
            </div>
            <div className="incident-card-foot">
              <span>
                <Layers3 size={14} />
                {i.count} alerts → 1 incident
              </span>
              <span>
                Inspect explanation <ChevronRight size={15} />
              </span>
            </div>
          </button>
        ))}
      </div>
      {!list.length && (
        <Empty text="No incidents match the selected region and severity." />
      )}
    </>
  );
}

function Proof() {
  const { mode, proof, updatedAt } = useData();
  const live = mode === "live";
  const fmt = (v, digits = 1) => (v == null ? "—" : Number(v).toFixed(digits));
  const m = live
    ? {
        dash: proof?.p95_dashboard_latency_s,
        alert: proof?.max_alert_delay_s,
        offline: proof?.offline_detection_s,
        received: proof?.received_unique,
        dup: proof?.stored_duplicates,
      }
    : { dash: 2.4, alert: 4.8, offline: 52, received: 1248, dup: 0 };
  const evidence = live
    ? { mode: "live", captured_at: new Date().toISOString(), ...(proof || {}) }
    : {
        mode: "demo",
        note: "Illustrative fixtures; not measurements from a running backend.",
        dashboard_p95_s: 2.4,
        alert_delay_s: 4.8,
        offline_detection_s: 52,
        sent_unique: 1248,
        received_unique: 1248,
        duplicates_stored: 0,
      };
  const tests = [
    { label: "Collection to dashboard", value: m.dash, target: 10, targetText: "≤ 10 s · p95", icon: Activity },
    { label: "Breach to alert", value: m.alert, target: 15, targetText: "≤ 15 s", icon: Bell },
    { label: "Offline detection", value: m.offline, target: 60, targetText: "≤ 60 s", icon: WifiOff },
  ];
  return (
    <>
      <div className="notice">
        <CircleHelp size={18} />
        <span>
          {live
            ? "Recent five-minute window, measured using payload and client-reported timestamps. Clock skew affects latency; a blank value means that measurement has not happened yet. Sent counts live only on the collector."
            : "These are illustrative demo results. Connect timestamped stream evidence before presenting performance claims."}
        </span>
      </div>
      {live && <p className="proof-sample-info">Dashboard samples: {proof?.dashboard_samples ?? 0} · Window: {proof?.window_s != null ? `${proof.window_s} s` : "Unavailable"} · Last updated: {updatedAt ? new Date(updatedAt).toLocaleTimeString() : "Unavailable"}</p>}
      <div className="proof-grid">
        {tests.map((t) => {
          const has = t.value != null;
          const ok = has && t.value <= t.target;
          return (
            <section key={t.label} className="panel proof-card">
              <IconBox icon={t.icon} />
              <h2>{t.label}</h2>
              <div className="proof-value">
                {fmt(t.value, t.label === "Offline detection" ? 0 : 1)}
                <span>s</span>
              </div>
              <div className="proof-target">
                {has ? <Check size={15} /> : <CircleHelp size={15} />}
                {!has ? "Not measured yet" : ok ? (live ? "Within target" : "Within demo target") : "Above target"}{" "}
                <span>{t.targetText}</span>
              </div>
              <div className="target-track">
                <span style={{ width: `${has ? Math.min(100, (t.value / t.target) * 100) : 0}%` }} />
              </div>
              <div className="target-labels">
                <span>0 s</span>
                <span>Target</span>
              </div>
            </section>
          );
        })}
      </div>
      <section className="panel">
        <PanelTitle icon={Database} title="Outage recovery & delivery">
          <button
            className="button small"
            onClick={() =>
              downloadJSON(live ? "signal-labs-proof.json" : "signal-labs-demo-proof.json", evidence)
            }
          >
            <Download size={14} />
            {live ? "Export evidence" : "Export demo evidence"}
          </button>
        </PanelTitle>
        <div className="delivery-grid">
          <div>
            <span>Unique payloads sent</span>
            <strong>{live ? "—" : "1,248"}</strong>
          </div>
          <div>
            <span>Unique payloads received</span>
            <strong>{m.received == null ? "—" : Number(m.received).toLocaleString()}</strong>
          </div>
          <div>
            <span>Missing payloads</span>
            <strong className={live ? "" : "text-green"}>{live ? "—" : "0"}</strong>
          </div>
          <div>
            <span>Duplicates stored</span>
            <strong className={m.dup === 0 ? "text-green" : ""}>{m.dup == null ? "—" : m.dup}</strong>
          </div>
        </div>
        <div className="delivery-flow">
          <span>
            <Database size={19} />
            Local outbox
          </span>
          <i />
          <span>
            <RefreshCw size={19} />
            Retry + replay
          </span>
          <i />
          <span>
            <CheckCheck size={19} />
            Deduplicated ingest
          </span>
        </div>
        <div className="panel-bottom">
          {live
            ? "Sent IDs live only on the collector. Export this evidence, then compare its received ID list with the collector's local egress log; equal counts alone do not prove zero loss."
            : "For live validation, compare unique payload ID sets after reconnection; equal counts alone do not prove zero loss."}
        </div>
      </section>
      <section className="panel methodology">
        <PanelTitle icon={Clock3} title="How evidence should be measured" />
        <div>
          <article>
            <span className="eyebrow">Dashboard latency</span>
            <p>
              Dashboard render time minus source event time. Report the 95th
              percentile over a stated sample window.
            </p>
          </article>
          <article>
            <span className="eyebrow">Alert and offline time</span>
            <p>
              Compare the injected breach with alert creation, and the last
              heartbeat with the transition to Poor.
            </p>
          </article>
          <article>
            <span className="eyebrow">Delivery integrity</span>
            <p>
              Compare sent and received unique IDs. Retries can repeat on the
              wire; each payload should be stored once.
            </p>
          </article>
        </div>
      </section>
    </>
  );
}

function Egress({ notify }) {
  const [showRaw, setShowRaw] = useState(false);
  return (
    <>
      <div className="local-banner">
        <LockKeyhole size={20} />
        <div>
          <strong>Local collector workspace</strong>
          <p>
            This demo uses synthetic records. In production, raw records must be
            served only within the customer environment.
          </p>
        </div>
        <span className="small-tag">Synthetic data</span>
      </div>
      <div className="pipeline">
        {[
          "Collect",
          "Redact",
          "Aggregate",
          "Analyze",
          "Policy gate",
          "Send",
        ].map((s, i) => (
          <React.Fragment key={s}>
            <span className={s === "Policy gate" ? "gate" : ""}>
              {s === "Policy gate" ? (
                <ShieldCheck size={16} />
              ) : (
                <Check size={14} />
              )}{" "}
              {s}
            </span>
            {i < 5 && <ChevronRight size={14} />}
          </React.Fragment>
        ))}
      </div>
      <div className="egress-grid">
        <section className="panel">
          <PanelTitle icon={Terminal} title="Raw record · stays local">
            <span className="small-tag amber">Never exported</span>
          </PanelTitle>
          <div className="code-label">Synthetic authentication record</div>
          {showRaw ? (
            <pre className="raw-code">{`2026-11-20T09:15:00Z\n\nhost=internal-auth-01\nsource_ip=10.2.4.7\nuser=alice@example.test\npassword=DEMO_SECRET_NOT_REAL\nresult=failed\n\n42 failures within 60 seconds`}</pre>
          ) : (
            <div className="raw-hidden">
              <LockKeyhole size={30} />
              <h3>Raw details stay here</h3>
              <p>
                Reveal a synthetic record to compare it with the approved
                outgoing summary.
              </p>
              <button className="button" onClick={() => setShowRaw(true)}>
                Reveal demo record
              </button>
            </div>
          )}
          <div className="panel-bottom">
            <ShieldX size={14} />
            Usernames, original IPs, passwords, and raw lines are excluded.
          </div>
        </section>
        <section className="panel">
          <PanelTitle icon={FileJson} title="Approved outgoing payload">
            <button
              className="icon-button"
              aria-label="Copy outgoing payload"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    JSON.stringify(egress, null, 2),
                  );
                  notify("Demo payload copied");
                } catch {
                  notify(
                    "Clipboard unavailable. Use Download payload instead.",
                  );
                }
              }}
            >
              <Copy size={16} />
            </button>
          </PanelTitle>
          <div className="code-label">
            <span className="tiny-dot green" />
            Allow-listed metadata · demo
          </div>
          <pre className="json-code">{JSON.stringify(egress, null, 2)}</pre>
          <div className="panel-bottom">
            <Check size={14} />
            Structured summary. No raw authentication record.
          </div>
        </section>
      </div>
      <section className="panel">
        <PanelTitle icon={ShieldCheck} title="What changed at the boundary">
          <button
            className="button small"
            onClick={() => downloadJSON("signal-labs-demo-egress.json", egress)}
          >
            <Download size={14} />
            Download payload
          </button>
        </PanelTitle>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Input field</th>
                <th>Local treatment</th>
                <th>Outgoing value</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="mono">password, user</td>
                <td>
                  <Badge state="Dropped" />
                </td>
                <td className="muted">Excluded from outgoing schema</td>
              </tr>
              <tr>
                <td className="mono">source_ip, host</td>
                <td>
                  <Badge state="Pseudonymized" />
                </td>
                <td className="mono">src_9fa2c1</td>
              </tr>
              <tr>
                <td className="mono">raw login records</td>
                <td>
                  <Badge state="Aggregated" />
                </td>
                <td>42 failures · 60-second window</td>
              </tr>
              <tr>
                <td className="mono">free-text message</td>
                <td>
                  <Badge state="Replaced" />
                </td>
                <td>Template: repeated failed logins</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function Dashboard() {
  const { collectors, incidents, cpuSeries, latencySeries, analyticsSeries, proof, session, mode, status, error, updatedAt, refresh } = useData();
  const [page, setPage] = useState(currentPage);
  const [region, setRegion] = useState("in");
  useEffect(() => { if (mode === "live" && session?.region) setRegion(session.region); }, [mode, session?.region]);
  const [range, setRange] = useState("1h");
  const [detail, setDetail] = useState(null);
  const [toast, setToast] = useState("");
  const [help, setHelp] = useState(false);
  useEffect(() => {
    const change = () => {
      setPage(currentPage());
      setDetail(null);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    document.title = `Signal Labs · ${pages[page][0]}`;
    const navigation = document.querySelector('.top-nav');
    const active = navigation?.querySelector('[aria-current="page"]');
    if (navigation && active) {
      const left = active.getBoundingClientRect().left - navigation.getBoundingClientRect().left;
      navigation.scrollLeft += left - 12;
    }
  }, [page]);
  useEffect(() => {
    const key = (e) => {
      if (e.key === "Escape") {
        setDetail(null);
        setHelp(false);
        }
      if (
        e.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(
          document.activeElement?.tagName,
        )
      ) {
        const input = document.querySelector(
          'input[aria-label="Search collectors"]',
        );
        if (input) {
          e.preventDefault();
          input.focus();
        }
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!help) return;
    const previous = document.activeElement;
    const dialog = document.querySelector(".guide-modal");
    const controls = [...dialog.querySelectorAll("button, a[href]")];
    controls[0]?.focus();
    const trap = (e) => {
      if (e.key !== "Tab") return;
      if (e.shiftKey && document.activeElement === controls[0]) {
        e.preventDefault();
        controls.at(-1)?.focus();
      }
      if (!e.shiftKey && document.activeElement === controls.at(-1)) {
        e.preventDefault();
        controls[0]?.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      previous?.focus?.();
    };
  }, [help]);
  const rows = collectors.filter(
    (c) => region === "all" || c.region === region,
  );
  return (
    <div className="app-shell">
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <a className="image-brand" href="#/fleet" aria-label="Signal Labs home"><img src="/signal-labs-transparent.png" alt="Signal Labs" /></a>
            <span className="header-divider" />
            <div className="header-workspace"><span>{mode === "live" ? "Authenticated tenant" : "Workspace"}</span><strong>{mode === "live" ? (session?.tenant_id || "Unavailable") : "Team Mirai"}</strong></div>
            <span className="header-environment">Observability platform</span>
          </div>
          <div className="topbar-right">
            <button className="icon-button header-help" aria-label="Open demo guide" onClick={() => setHelp(true)}><CircleHelp size={18}/></button>
            <button className="icon-button notification-button" aria-label="Open incidents" onClick={() => { location.hash = "#/incidents"; }}><Bell size={18}/><i className="notification-dot" /></button>
            {mode === "live" ? <UserMenu /> : <span className="top-avatar" title="Demo data">M</span>}
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              {page === "egress" && <div className="eyebrow">Local collector, synthetic records</div>}
              <h1>
                {pages[page][0]}

              </h1>
              <p>{pages[page][1]}</p>
            </div>
            <div className="heading-actions">
              {page !== "egress" && page !== "proof" && (
                <label className="select-wrap region-select">
                  <Globe2 size={15} />
                  <select
                    value={region}
                    aria-label="Region"
                    disabled={mode === "live"}
                    onChange={(e) => setRegion(e.target.value)}
                  >
                    <option value="in">India · IN</option>
                    <option value="eu">Europe · EU</option>
                    <option value="all">All regions · demo</option>
                  </select>
                  <ChevronDown size={13} />
                </label>
              )}
              {page === "fleet" && (
                <label className="select-wrap">
                  <Clock3 size={15} />
                  <select
                    aria-label="Chart time range"
                    value={range}
                    onChange={(e) => setRange(e.target.value)}
                  >
                    <option value="1h">Last hour</option>
                    <option value="15m">Last 15 min</option>
                  </select>
                  <ChevronDown size={13} />
                </label>
              )}
              <button
                className="icon-button refresh-button"
                aria-label={mode === "live" ? "Refresh live data" : "Refresh demo snapshot"}
                onClick={() => {
                  if (mode === "live") {
                    refresh();
                    setToast("Refreshing from the SaaS…");
                  } else {
                    setToast("Demo snapshot refreshed. Backend is not connected.");
                  }
                }}
              >
                <RefreshCw size={16} />
              </button>
            </div>
          </div>
          <nav className="top-nav" aria-label="Dashboard views">
            {nav.filter((n) => !n.adminOnly || session?.permissions?.includes("users.manage")).map((n) => <a key={n.id} href={`#/${n.id}`} className={page === n.id ? 'active' : ''} aria-current={page === n.id ? 'page' : undefined}>{n.label}{n.id === 'incidents' && <span className="nav-count">{incidents.filter(i => region === 'all' || i.region === region).length}</span>}</a>)}
            <a className="nav-cta" href="#/incidents">Review incidents <span>{incidents.filter(i => region === 'all' || i.region === region).length}</span></a>
          </nav>
          {mode === "live" && session && <p className="tenant-scope">Tenant: <strong>{session.tenant_id}</strong> · Region: {session.region.toUpperCase()} · Role: <strong>{session.role}</strong> · Sign out from the account menu to switch person.</p>}
          {mode === "live" && status === "loading" && (
            <div className="notice">
              <RefreshCw size={18} />
              <span>Loading live data from the SaaS…</span>
            </div>
          )}
          {mode === "live" && status === "error" && (
            <div className="notice">
              <WifiOff size={18} />
              <span>
                Cannot reach the SaaS ({error}).{" "}
                {updatedAt
                  ? `Showing the last data from ${new Date(updatedAt).toLocaleTimeString()}; it may be stale.`
                  : "No data has been received yet."}
              </span>
            </div>
          )}
          {page === "fleet" && (
            <Fleet
              rows={rows}
              range={range}
              onSelect={(c) => setDetail({ type: "collector", item: c })}
              onIncident={(i) => setDetail({ type: "incident", item: i })}
            />
          )}
          {page === "flow" && <DataFlow collectors={rows} incidents={incidents} region={region} mode={mode} />}
          {page === "analytics" && <Analytics collectors={rows} incidents={incidents.filter(i => region === "all" || i.region === region)} region={region} mode={mode} proof={proof} cpuSeries={cpuSeries} latencySeries={latencySeries} analyticsSeries={analyticsSeries} onSelectCollector={(c) => setDetail({ type: "collector", item: c })} />}
          {page === "incidents" && (
            <Incidents
              region={region}
              onSelect={(i) => setDetail({ type: "incident", item: i })}
            />
          )}
          {page === "proof" && <Proof />}
          {page === "received" && <ReceivedPayload />}
          {page === "objects" && <ObjectExplorer />}
          {page === "history" && <HealthHistory />}
          {page === "egress" && <Egress notify={setToast} />}
          {page === "users" && <UsersAdmin />}
          <footer>
            <span>
              <Activity size={13} />
              Signal Labs <span>·</span> Built for CICADA 2026
            </span>
          </footer>
        </main>
      </div>
      {detail && <Detail detail={detail} close={() => setDetail(null)} />}
      {help && (
        <div className="modal-backdrop" onClick={() => setHelp(false)}>
          <section
            className="guide-modal panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="guide-title"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              autoFocus
              className="icon-button modal-close"
              aria-label="Close guide"
              onClick={() => setHelp(false)}
            >
              <X size={20} />
            </button>
            <IconBox icon={Sparkles} />
            <h2 id="guide-title">Your platform, at a glance.</h2>
            <p>
              Start with collector health, inspect an incident, check delivery
              evidence, then explain the privacy boundary.
            </p>
            {nav.map((n) => (
              <a href={`#/${n.id}`} key={n.id} onClick={() => setHelp(false)}>
                <n.icon size={19} />
                <span>{n.label}</span>
                <ChevronRight size={16} />
              </a>
            ))}
            <div className="notice">
              All records and performance values are mock data. No collector or
              SaaS connection is active.
            </div>
          </section>
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <Check size={16} />
          {toast}
        </div>
      )}
    </div>
  );
}

function Detail({ detail, close }) {
  const { mode } = useData();
  const { type, item } = detail;
  const closeRef = React.useRef(null);
  useEffect(() => {
    const previous = document.activeElement;
    closeRef.current?.focus();
    const trap = (e) => {
      if (e.key !== "Tab") return;
      const drawer = closeRef.current?.closest('[role="dialog"]');
      const controls = [...(drawer?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled])') || [])];
      if (!controls.length) return;
      if (e.shiftKey && document.activeElement === controls[0]) { e.preventDefault(); controls.at(-1).focus(); }
      if (!e.shiftKey && document.activeElement === controls.at(-1)) { e.preventDefault(); controls[0].focus(); }
    };
    document.addEventListener("keydown", trap);
    return () => {
      document.removeEventListener("keydown", trap);
      previous?.focus?.();
    };
  }, []);
  return (
    <div className="drawer-backdrop" onClick={close}>
      <section
        className="detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-top">
          <span className="eyebrow">
            {type === "collector" ? "Collector details" : "Explainable AIOps"} ·{" "}
            {mode === "live" ? "LIVE" : "DEMO"}
          </span>
          <button
            className="icon-button"
            ref={closeRef}
            onClick={close}
            aria-label="Close details"
          >
            <X size={20} />
          </button>
        </div>
        <IconBox icon={type === "collector" ? Server : Sparkles} />
        <h2 id="detail-title">
          {type === "collector" ? item.name : item.title}
        </h2>
        <span className="mono muted">{item.id}</span>
        <div className="drawer-section">
          <Badge state={type === "collector" ? item.state : item.severity} />
          <p>{type === "collector" ? item.reason : item.description}</p>
        </div>
        {type === "collector" ? (
          <>
            <h3>Current signals</h3>
            <div className="detail-signals">
              {[
                ["CPU", item.cpu == null ? "Unavailable" : `${item.cpu}%`],
                [
                  "Memory",
                  item.memory == null ? "Unavailable" : `${item.memory}%`,
                ],
                [
                  "Latency",
                  item.latency == null ? "Unavailable" : `${item.latency} ms`,
                ],
                [
                  "Packet loss",
                  item.loss == null ? "Unavailable" : `${item.loss}%`,
                ],
                ["Last heartbeat", ago(item.seen)],
                ["Version", item.version],
                ["Source", item.source],
                ["Region", regionName[item.region]],
              ].map(([label, value]) => (
                <div key={label}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                </div>
              ))}
            </div>
            <div className="notice">
              <LockKeyhole size={17} />
              <span>
                Raw logs are not available in the central dashboard. Inspect
                them inside the customer environment.
              </span>
            </div>
          </>
        ) : (
          <>
            <h3>Contributing signals</h3>
            <div className="detail-signals">
              {item.signals.map((s) => (
                <div key={s.name}>
                  <span>
                    {s.name}
                    <small>{s.baseline}</small>
                  </span>
                  <strong>{s.value}</strong>
                </div>
              ))}
            </div>
            <div className="recommendation">
              <span className="eyebrow">
                <Sparkles size={14} />
                RECOMMENDED INVESTIGATION
              </span>
              <p>{item.action}</p>
            </div>
            <h3>Why this recommendation?</h3>
            <p className="detail-body">{item.reasoning}</p>
            <div className="confidence">
              <span>Heuristic confidence</span>
              <strong>{item.confidence}</strong>
            </div>
            <IncidentWorkspace incidentId={item.id} mode={mode} />
            <div className="notice">
              <CircleHelp size={17} />
              <span>
                {mode === "live"
                  ? "Heuristic, rule-based explanation from metadata only."
                  : "Illustrative rule-based explanation."}{" "}
                No automated action has been executed.
              </span>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

// Collector health as a wheel of four rounded segments, one per state. A segment's filled part grows outward from the
// centre with that state's share of the fleet, so the biggest group is the first thing the eye finds. Colours are the
// dashboard's own state colours; the numbers and names sit on the segments so no separate legend is needed.
const WHEEL_STATES = [
  { state: "Excellent", fill: "#2f69ec", ink: "#ffffff" },
  { state: "Good", fill: "#93b8fc", ink: "#0f2347" },
  { state: "Fair", fill: "#f36b34", ink: "#2b1405" },
  { state: "Poor", fill: "#aeb4bb", ink: "#1f2433" },
];
function polar(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}
function sector(cx, cy, r0, r1, a0, a1) {
  const [x0, y0] = polar(cx, cy, r1, a0), [x1, y1] = polar(cx, cy, r1, a1);
  const [x2, y2] = polar(cx, cy, r0, a1), [x3, y3] = polar(cx, cy, r0, a0);
  return `M${x0} ${y0}A${r1} ${r1} 0 0 1 ${x1} ${y1}L${x2} ${y2}A${r0} ${r0} 0 0 0 ${x3} ${y3}Z`;
}
function StatusWheel({ counts, total }) {
  const size = 280, c = size / 2, hole = 34, outer = 132, round = 7, gap = 5;
  const summary = WHEEL_STATES.map((w) => `${counts[w.state] || 0} ${w.state.toLowerCase()}`).join(", ");
  return (
    <svg className="status-wheel" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={`Collector health: ${summary} of ${total}`}>
      {WHEEL_STATES.map((w, i) => {
        const n = counts[w.state] || 0;
        const a0 = -90 + i * 90 + gap / 2, a1 = -90 + (i + 1) * 90 - gap / 2;
        const reach = n ? hole + (outer - hole) * Math.max(n / Math.max(total, 1), 0.16) : 0;
        const mid = (a0 + a1) / 2;
        const [tx, ty] = polar(c, c, hole + (outer - hole) * 0.56, mid);
        const covered = reach >= hole + (outer - hole) * 0.56;
        const ink = covered ? w.ink : "#4b5563";
        const shape = (r0, r1) => sector(c, c, r0 + round / 2, r1 - round / 2, a0 + 2.2, a1 - 2.2);
        return (
          <g key={w.state}>
            <title>{`${w.state}: ${n} of ${total} collectors`}</title>
            <path d={shape(hole, outer)} fill="#eceff3" stroke="#eceff3" strokeWidth={round} strokeLinejoin="round" />
            {n > 0 && <path d={shape(hole, reach)} fill={w.fill} stroke={w.fill} strokeWidth={round} strokeLinejoin="round" />}
            <text className="wheel-count" x={tx} y={ty - 2} textAnchor="middle" fill={ink}>{n}</text>
            <text className="wheel-name" x={tx} y={ty + 15} textAnchor="middle" fill={ink}>{w.state}</text>
          </g>
        );
      })}
    </svg>
  );
}

// "17787 s" is unreadable: show "4 h ago". Stale and offline follow the platform's thresholds (30 s and 40 s).
function ago(seconds) {
  if (seconds < 90) return `${seconds} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}
function presence(c) {
  if (c.online === false) return { label: "Offline", cls: "text-red" };
  if (c.seen > 30) return { label: "Stale", cls: "text-amber" };
  return { label: "Live", cls: "muted" };
}
function resourceText(r) {
  const parts = [["cpu", r.cpu_percent], ["mem", r.memory_percent], ["disk", r.disk_percent]].filter(([, v]) => v != null).map(([k, v]) => `${k} ${v}%`);
  return parts.length ? parts.join(" · ") : "no resource report";
}

export default function App() {
  const live = useLiveData();
  const value = LIVE
    ? {
        mode: "live",
        session: live.data?.session ?? null,
        collectors: live.data?.collectors ?? [],
        incidents: live.data?.incidents ?? [],
        cpuSeries: live.data?.cpuSeries ?? [],
        latencySeries: live.data?.latencySeries ?? [],
        analyticsSeries: live.data?.analyticsSeries ?? null,
        proof: live.data?.proof ?? null,
        status: live.status,
        error: live.error,
        updatedAt: live.updatedAt,
        refresh: live.refresh,
      }
    : {
        mode: "demo",
        collectors: demoCollectors,
        incidents: demoIncidents,
        cpuSeries: demoCpu,
        latencySeries: demoLatency,
        analyticsSeries: null,
        proof: null,
        status: "demo",
        error: null,
        updatedAt: null,
        refresh: () => {},
      };
  return (
    <DataContext.Provider value={value}>
      <Dashboard />
    </DataContext.Provider>
  );
}
