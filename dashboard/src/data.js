// Fixtures only. Replace this adapter after Member A/B freeze response shapes.
export const collectors = [
  {
    id: "col-blr-01",
    name: "Bengaluru · Production",
    source: "src_9fa2c1",
    region: "in",
    state: "Excellent",
    cpu: 32,
    memory: 48,
    latency: 24,
    loss: 0.1,
    seen: 2,
    version: "0.3.1",
    reason: "All signals within the expected baseline.",
  },
  {
    id: "col-blr-02",
    name: "Bengaluru · API cluster",
    source: "src_8bb4d2",
    region: "in",
    state: "Fair",
    cpu: 91,
    memory: 76,
    latency: 186,
    loss: 1.8,
    seen: 4,
    version: "0.3.1",
    reason:
      "CPU above baseline with elevated service latency for three windows.",
  },
  {
    id: "col-mum-01",
    name: "Mumbai · Edge",
    source: "src_2ca9e8",
    region: "in",
    state: "Good",
    cpu: 54,
    memory: 61,
    latency: 42,
    loss: 0.3,
    seen: 3,
    version: "0.3.1",
    reason: "Minor latency deviation; no significant service impact.",
  },
  {
    id: "col-del-01",
    name: "Delhi · Gateway",
    source: "src_3ef7b1",
    region: "in",
    state: "Poor",
    cpu: null,
    memory: null,
    latency: null,
    loss: null,
    seen: 84,
    version: "0.3.0",
    reason:
      "Heartbeat missing for 84 seconds. Last values are stale and hidden.",
  },
  {
    id: "col-hyd-01",
    name: "Hyderabad · Services",
    source: "src_6dd1a4",
    region: "in",
    state: "Excellent",
    cpu: 28,
    memory: 42,
    latency: 19,
    loss: 0,
    seen: 1,
    version: "0.3.1",
    reason: "All signals within the expected baseline.",
  },
  {
    id: "col-fra-01",
    name: "Frankfurt · EU production",
    source: "src_7ec3f6",
    region: "eu",
    state: "Excellent",
    cpu: 38,
    memory: 52,
    latency: 28,
    loss: 0.1,
    seen: 2,
    version: "0.3.1",
    reason: "All signals within the expected baseline.",
  },
];

export const incidents = [
  {
    id: "INC-024",
    title: "Resource saturation on API cluster",
    severity: "High",
    collector: "col-blr-02",
    region: "in",
    time: "2 min ago",
    count: 8,
    category: "Performance",
    description:
      "Sustained CPU deviation and increased latency occurred on the same source within a 60-second window.",
    signals: [
      { name: "CPU utilization", value: "91%", baseline: "Expected 28–45%" },
      {
        name: "Service latency",
        value: "186 ms",
        baseline: "Expected 20–40 ms",
      },
      {
        name: "Persistence",
        value: "3 windows",
        baseline: "5 seconds per window",
      },
    ],
    action:
      "Inspect running processes and recent deployments. Confirm resource pressure before scaling the service.",
    confidence: "Moderate",
    reasoning:
      "The timing and source match suggest resource contention. These signals do not establish a root cause.",
  },
  {
    id: "INC-023",
    title: "Collector heartbeat missing",
    severity: "Critical",
    collector: "col-del-01",
    region: "in",
    time: "1 min ago",
    count: 1,
    category: "Availability",
    description:
      "No heartbeat received for 84 seconds. The collector has exceeded the 60-second offline window.",
    signals: [
      {
        name: "Last heartbeat",
        value: "84 s ago",
        baseline: "Expected every 10 s",
      },
      {
        name: "Offline threshold",
        value: "60 s",
        baseline: "Configured timeout",
      },
    ],
    action:
      "Check collector process and network reachability. Do not assume monitored services are down solely because a collector is unreachable.",
    confidence: "High",
    reasoning:
      "Missing heartbeats confirm a monitoring gap. Service availability requires a separate check.",
  },
  {
    id: "INC-022",
    title: "Repeated authentication failures",
    severity: "Medium",
    collector: "col-blr-01",
    region: "in",
    time: "8 min ago",
    count: 12,
    category: "Security",
    description:
      "The local collector summarized 42 failed logins in one minute. Raw authentication records remain local.",
    signals: [
      {
        name: "Failed logins",
        value: "42 / min",
        baseline: "Expected 0–3 / min",
      },
      {
        name: "Source",
        value: "src_9fa2c1",
        baseline: "Pseudonymous identifier",
      },
    ],
    action:
      "Review the local authentication records and check for misconfigured clients or suspicious activity before restricting access.",
    confidence: "Moderate",
    reasoning:
      "A failure burst is unusual, but may also come from expired service credentials.",
  },
];

export const cpuSeries = [
  31, 34, 30, 32, 36, 33, 32, 38, 35, 31, 34, 33, 39, 36, 40, 38, 35, 42, 40,
  46, 52, 71, 82, 78, 91, 87, 92, 88, 91,
];
export const latencySeries = [
  22, 24, 21, 25, 28, 22, 26, 23, 29, 25, 23, 28, 25, 29, 30, 25, 28, 34, 32,
  38, 90, 135, 158, 142, 168, 160, 176, 164, 186,
];

export const egress = {
  payload_id: "b3f1a908-6e2d-4c72-a941-83d09f052e61",
  collector_id: "col-blr-01",
  source_id: "src_9fa2c1",
  region: "in",
  event_ts_utc: "2026-11-20T09:15:00Z",
  source_tz: "Asia/Kolkata",
  window_s: 60,
  event: {
    category: "auth_failure_burst",
    severity: "high",
    count: 42,
    summary: "repeated failed logins",
  },
  health_state: "Fair",
  collector_version: "0.3.1",
};
