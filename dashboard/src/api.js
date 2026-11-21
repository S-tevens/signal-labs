// Live adapter: SaaS API responses -> the shapes the views already use (see data.js).
//
// Live mode is the default: people sign in, and the platform issues a short-lived session token that is kept in
// sessionStorage (it ends with the tab). Set VITE_DEMO_MODE=1 to see labelled demo data without a platform.
// In live mode a failed request is shown as an error with the last good data marked stale.
// It never silently falls back to demo values. VITE_DEV_TOKEN is an optional developer shortcut (an API token);
// leave it unset. Collector secrets must never be used here.
import { useCallback, useEffect, useRef, useState } from "react";

const DEV_TOKEN = import.meta.env.VITE_DEV_TOKEN || "";
const SESSION_KEY = "signal-labs-session";
// "/api" is proxied to the SaaS by vite.config.js in dev (same origin, so no CORS).
const BASE = (import.meta.env.VITE_SAAS_URL || "/api").replace(/\/$/, "");
export const LIVE = import.meta.env.VITE_DEMO_MODE !== "1";

export function getSession() {
  try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null"); } catch { return null; }
}
export function saveSession(session) {
  try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(session)); } catch { /* storage may be blocked */ }
  window.dispatchEvent(new Event("signal-session-changed"));
}
export function clearSession() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch { /* nothing to clear */ }
  window.dispatchEvent(new Event("signal-session-changed"));
}
export function currentToken() {
  const s = getSession();
  return (s && s.expires_at * 1000 > Date.now() ? s.token : "") || DEV_TOKEN;
}
export const isSignedIn = () => currentToken() !== "";

async function problem(res, path) {
  const detail = await res.json().then((j) => (typeof j.detail === "string" ? j.detail : null)).catch(() => null);
  return Object.assign(new Error(detail || `${path.split("?")[0]} returned HTTP ${res.status}`), { status: res.status });
}

export async function login(tenant, username, password) {
  const res = await fetch(`${BASE}/v1/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tenant, username, password }) });
  if (!res.ok) throw await problem(res, "/v1/login");
  const body = await res.json();
  saveSession({ token: body.token, expires_at: body.expires_at, user: body.user, tenant });
  return body;
}

export async function logout() {
  try { await request("/v1/logout", { method: "POST" }); } catch { /* the token is dropped either way */ }
  clearSession();
  window.dispatchEvent(new Event("signal-signed-out"));
}

const POLL_MS = 3000;
const PUSH_COALESCE_MS = 1000;
const WINDOW_MS = 30 * 60 * 1000; // /v1/metrics returns oldest-first and is capped, so bound the window
const METRICS = { cpu_pct: "cpu", mem_pct: "memory", latency_ms: "latency", packet_loss_pct: "loss" };

export async function request(path, { signal, method = "GET", body } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    signal,
    headers: { Authorization: `Bearer ${currentToken()}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  if (res.status === 401 && getSession()) {
    // The session ended (expired, signed out elsewhere, or the account was disabled): go back to the sign-in screen.
    clearSession();
    window.dispatchEvent(new Event("signal-signed-out"));
  }
  if (!res.ok) throw await problem(res, path);
  return res.json();
}

const round1 = (n) => Math.round(n * 10) / 10;
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function relative(iso) {
  const s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (Number.isNaN(s)) return "—";
  if (s < 60) return `${s} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

// Average all collectors' readings into ~10 s buckets for the trend chart.
function series(points, buckets = 29) {
  const by = new Map();
  for (const p of points) {
    const k = Math.floor(Date.parse(p.event_ts_utc) / 10000);
    const b = by.get(k) || { sum: 0, n: 0 };
    b.sum += p.metric.value;
    b.n += 1;
    by.set(k, b);
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .slice(-buckets)
    .map(([, b]) => round1(b.sum / b.n));
}

function mapCollectors(fleet, metricsByName, sessionRegion) {
  // Latest reading per (collector, source, metric), then averaged across a collector's sources.
  const latest = new Map();
  const info = new Map();
  for (const [name, rows] of Object.entries(metricsByName)) {
    for (const m of rows) {
      const key = `${m.collector_id}|${m.source_id}|${name}`;
      const prev = latest.get(key);
      if (!prev || m.event_ts_utc > prev.ts) latest.set(key, { ts: m.event_ts_utc, value: m.metric.value });
      if (!info.has(m.collector_id)) info.set(m.collector_id, { source: m.source_id, region: m.region });
    }
  }
  const avg = (collector, name) => {
    const vals = [...latest.entries()]
      .filter(([k]) => k.startsWith(`${collector}|`) && k.endsWith(`|${name}`))
      .map(([, v]) => v.value);
    return vals.length ? round1(vals.reduce((a, b) => a + b, 0) / vals.length) : null;
  };
  return fleet.map((f) => {
    const id = f.collector_id || f.id;
    const meta = info.get(id) || {};
    const fresh = f.online !== false; // stale collectors hide their last values instead of showing them
    return {
      id,
      name: id,
      source: meta.source || "—",
      region: meta.region || sessionRegion,
      state: f.state,
      online: f.online !== false,
      cpu: fresh ? avg(id, "cpu_pct") : null,
      memory: fresh ? avg(id, "mem_pct") : null,
      latency: fresh ? avg(id, "latency_ms") : null,
      loss: fresh ? avg(id, "packet_loss_pct") : null,
      seen: Math.max(0, Math.round((Date.now() - Date.parse(f.last_seen_utc)) / 1000)),
      version: f.version || "—",
      reason: f.reason || "",
      configHash: f.config_hash || "—",
      resources: f.resources || {},
    };
  });
}

const SEVERITY = { critical: "Critical", high: "High" };
const CATEGORY = { cpu: "Performance", memory: "Performance", latency: "Performance", loss: "Network", auth: "Security", failed_login: "Security", packet_loss: "Network", offline: "Availability" };

function mapIncident(i, regionOf) {
  const rec = i.recommendation || {};
  const raw = i.signals || [];
  const groups = new Map();
  for (const s of raw) {
    const g = groups.get(s.signal) || { n: 0, max: -Infinity, method: s.method };
    g.n += 1;
    g.max = Math.max(g.max, Number(s.value));
    groups.set(s.signal, g);
  }
  const signals = [...groups.entries()].map(([name, g]) => ({
    name: cap(name.replace(/_/g, " ")),
    value: Number.isFinite(g.max) ? String(round1(g.max)) : "—",
    baseline: `${g.n} alert${g.n > 1 ? "s" : ""} · ${g.method || "rule"}`,
  }));
  signals.push({ name: "Source", value: i.source_id || "—", baseline: "Pseudonymous identifier" });
  const reasons = [...new Set(String(rec.why || "").split("; ").filter(Boolean))];
  const first = raw[0]?.signal;
  return {
    id: String(i.id),
    title: rec.likely_cause || "Correlated incident",
    severity: SEVERITY[i.severity] || "Medium",
    collector: i.collector_id,
    region: regionOf(i.collector_id),
    time: relative(i.last_ts),
    count: i.alert_count ?? raw.length,
    category: CATEGORY[first] || "Performance",
    description: `${i.alert_count ?? raw.length} related alerts grouped by source and time, from ${i.first_ts} to ${i.last_ts}.`,
    signals,
    action: rec.action || "No recommendation available.",
    confidence: cap(rec.confidence) || "—",
    reasoning: `${reasons.join("; ") || "No reasoning recorded"}. ${rec.confidence_type || ""}`.trim(),
  };
}

async function snapshot(signal) {
  const from = encodeURIComponent(new Date(Date.now() - WINDOW_MS).toISOString());
  const names = Object.keys(METRICS);
  const [fleet, incidents, proof, session, ...metricRows] = await Promise.all([
    request("/v1/fleet", { signal }),
    request("/v1/incidents", { signal }),
    request("/v1/proof?window_s=300", { signal }),
    request("/v1/session", { signal }),
    ...names.map((n) => request(`/v1/metrics?name=${n}&from=${from}&limit=10000`, { signal })),
  ]);
  const metricsByName = Object.fromEntries(names.map((n, i) => [n, metricRows[i]]));
  const collectors = mapCollectors(fleet, metricsByName, session.region);
  const regionOf = (id) => collectors.find((c) => c.id === id)?.region || session.region;
  const newest = names
    .flatMap((n) => metricsByName[n])
    // Only live arrivals count as renders. Acknowledging old payloads (a quiet system, or a page opened hours later)
    // would report their age as dashboard latency and make the p95 tile meaningless.
    .filter((m) => Date.now() - Date.parse(m.event_ts_utc) < 30000)
    .sort((a, b) => (a.received_ts_utc < b.received_ts_utc ? 1 : -1))
    .slice(0, 5)
    .map((m) => m.payload_id);
  return {
    collectors,
    incidents: incidents.map((i) => mapIncident(i, regionOf)),
    cpuSeries: series(metricsByName.cpu_pct),
    latencySeries: series(metricsByName.latency_ms),
    analyticsSeries: Object.fromEntries(["in", "eu", "all"].map((region) => [region, {
      cpu: series(metricsByName.cpu_pct.filter((m) => region === "all" || m.region === region)),
      latency: series(metricsByName.latency_ms.filter((m) => region === "all" || m.region === region)),
    }])),
    proof,
    session,
    newest,
  };
}

export function useLiveData() {
  const [state, setState] = useState({ status: LIVE ? "loading" : "demo", data: null, error: null, updatedAt: null });
  const acked = useRef(new Set());
  const seeded = useRef(false);

  const load = useCallback(async (signal) => {
    try {
      const data = await snapshot(signal);
      setState({ status: "ok", data, error: null, updatedAt: Date.now() });

    } catch (e) {
      if (e.name === "AbortError") return;
      setState((s) => ({ ...s, status: "error", error: e.message }));
    }
  }, []);

  // Acknowledge after React commits and the browser has had a paint opportunity.
  // This is client-reported timing, not proof of a physical screen refresh.
  useEffect(() => {
    if (!LIVE || !state.data) return undefined;
    let second;
    const first=requestAnimationFrame(() => { second=requestAnimationFrame(() => {
      if (!seeded.current) {
        // The first snapshot is whatever was already stored when the page opened, not a live arrival: remember it
        // without acknowledging, so opening the page late cannot inflate the dashboard latency.
        seeded.current = true;
        for (const id of state.data.newest) acked.current.add(id);
        return;
      }
      for (const id of state.data.newest) {
        if (acked.current.has(id)) continue;
        acked.current.add(id);
        request(`/v1/proof/render?payload_id=${encodeURIComponent(id)}`, {method:"POST"}).catch(() => acked.current.delete(id));
      }
    }); });
    return () => { cancelAnimationFrame(first); if (second != null) cancelAnimationFrame(second); };
  }, [state.data]);

  useEffect(() => {
    if (!LIVE) return undefined;
    const ctrl = new AbortController();
    let reconnectTimer, pushTimer;
    let inFlight = false, pending = false;
    const refresh = async () => {
      if (ctrl.signal.aborted) return;
      if (inFlight) { pending = true; return; }
      inFlight = true;
      try {
        do { pending = false; await load(ctrl.signal); } while (pending && !ctrl.signal.aborted);
      } finally { inFlight = false; }
    };
    const schedulePushRefresh = () => {
      if (pushTimer || ctrl.signal.aborted) return;
      pushTimer = setTimeout(() => { pushTimer = null; refresh(); }, PUSH_COALESCE_MS);
    };
    const connect = async () => {
      try {
        const res = await fetch(`${BASE}/v1/stream?mode=changes`, { headers: { Authorization: `Bearer ${currentToken()}` }, signal: ctrl.signal });
        if (!res.ok || !res.body) throw new Error(`Stream returned HTTP ${res.status}`);
        const reader = res.body.getReader(), decoder = new TextDecoder();
        let pending = '';
        while (!ctrl.signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          pending += decoder.decode(value, {stream:true}).replace(/\r\n/g, '\n');
          let end;
          while ((end = pending.indexOf('\n\n')) >= 0) {
            const event = pending.slice(0, end); pending = pending.slice(end + 2);
            if (event.includes('event: snapshot')) schedulePushRefresh();
          }
        }
      } catch (e) {
        if (e.name === 'AbortError') return;
      }
      if (!ctrl.signal.aborted) reconnectTimer = setTimeout(connect, 3000);
    };
    refresh(); connect();
    // A bounded fallback keeps proof data current while SSE reconnects.
    const timer = setInterval(refresh, POLL_MS * 3);
    return () => { ctrl.abort(); clearInterval(timer); clearTimeout(reconnectTimer); clearTimeout(pushTimer); };
  }, [load]);

  return { ...state, refresh: () => load() };
}
