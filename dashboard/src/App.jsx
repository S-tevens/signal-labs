import React, { useEffect, useState } from "react";

const SAAS = import.meta.env.VITE_SAAS_URL || "http://localhost:8080";
const TOKEN = "dash-acme"; // dev token; real login comes later

// Mock data matching contracts/api.md, used until the SaaS answers.
const MOCK_FLEET = [
  { collector_id: "col-blr-01", state: "Good", state_reason: "mock data", last_seen_utc: new Date().toISOString(), version: "0.1.0", buffer_depth: 0 },
];

const COLORS = { Excellent: "#1a9850", Good: "#66bd63", Fair: "#f9a825", Poor: "#d73027" };

export default function App() {
  const [fleet, setFleet] = useState(MOCK_FLEET);
  const [live, setLive] = useState(false);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch(`${SAAS}/v1/fleet`, { headers: { "X-Dashboard-Token": TOKEN } });
        if (!r.ok) throw new Error(r.status);
        const data = await r.json();
        if (!stop) { setFleet(data); setLive(true); }
      } catch {
        if (!stop) { setFleet(MOCK_FLEET); setLive(false); }
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { stop = true; clearInterval(id); };
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", maxWidth: 900, margin: "2rem auto", padding: "0 1rem" }}>
      <h1>Signal Labs</h1>
      <p>{live ? "Live data from the SaaS" : "Showing mock data (SaaS not reachable)"}</p>
      <h2>Fleet</h2>
      <table cellPadding={8} style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead><tr style={{ textAlign: "left" }}><th>Collector</th><th>State</th><th>Reason</th><th>Last seen (UTC)</th><th>Version</th><th>Buffered</th></tr></thead>
        <tbody>
          {fleet.map((c) => (
            <tr key={c.collector_id} style={{ borderTop: "1px solid #ddd" }}>
              <td>{c.collector_id}</td>
              <td><span style={{ background: COLORS[c.state], color: "#fff", padding: "2px 8px", borderRadius: 4 }}>{c.state}</span></td>
              <td>{c.state_reason}</td>
              <td>{c.last_seen_utc}</td>
              <td>{c.version}</td>
              <td>{c.buffer_depth}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ color: "#666" }}>Next: incidents, proof metrics and the egress panel.</p>
    </main>
  );
}
