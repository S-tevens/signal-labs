# Signal Labs: presentation story and plan

Team member names and exact checkpoint times must be confirmed by the team before the presentation.

**Before:** Operators looking after servers and networks can have information spread across different tools. A real issue may generate many warnings, while a monitoring agent that stops reporting can leave a misleading last-known-good value. Moving complete logs to a central service can expose sensitive details.

**What we observe:** Our proposed system shows each tenant's collector health, resource and network signals, security-event summaries, and correlated incidents. Each recommendation points back to retained metadata signals and payload IDs. A local proof view is intended to show what was removed before a payload crossed the customer boundary.

**Our four use cases:** infrastructure health (CPU, memory, disk); latency and packet loss; repeated login failures summarized locally; and collector online/offline health.

**One-minute pitch:** “Signal Labs helps operators understand distributed infrastructure without sending raw logs to the central platform. A collector inside the customer environment processes telemetry and sends approved metadata. Our SaaS shows fleet health, correlates abnormal signals and explains recommended investigations. Operators can trace incidents to their evidence and review simulated actions. The local proof panel will show exactly what leaves the customer environment.”

**Demo order:** run `.\scripts\demo.ps1 secret`, then show the collector's egress proof panel at `http://127.0.0.1:8101/local/ui`; follow the corresponding payload into the dashboard; open an incident, its evidence, and its simulated action audit; show health history and measured proof; then simulate an outage and compare sent and received IDs. Mark fixtures and synthetic tests clearly. TLS, real-host coverage and zero loss (by payload ID set, through an outage and a killed replica) have been verified live on one machine. Do not claim regional residency or the latency targets until they are measured.

**Team plan:** Member 1 owns collector, local policy, telemetry, TLS, simulator and start scripts. Member 2 owns the SaaS, dashboard, contract documentation, CI and story. Keep the payload schema unchanged unless both owners agree. Agree on the final API, certificate paths, checkpoint times and team names before the live demo.
