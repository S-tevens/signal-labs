// These are architectural explanations, not observations of a running deployment.
export const details = {
  infra: [
    ["CPU utilization", "Processor usage", "The collector reads CPU utilization from configured telemetry sources. A high value can indicate resource pressure."],
    ["Memory usage", "Working memory", "Memory measurements show how much available memory is being used. The signal is summarized before leaving the local environment."],
    ["Disk usage", "Storage capacity", "Disk utilization can indicate that a host is running out of capacity. Only approved measurements are sent to the platform."],
    ["Local source", "Host or service", "Each measurement is associated with a pseudonymous source so the platform can correlate it without receiving the original identity."],
  ],
  network: [
    ["Latency", "Response time", "Latency measures how long communication takes, usually in milliseconds. Rising latency may signal degraded connectivity."],
    ["Packet loss", "Lost traffic", "Packet loss is the percentage of network packets that fail to arrive. It is analyzed alongside latency rather than in isolation."],
    ["Bandwidth", "Traffic volume", "Bandwidth represents the amount of network traffic over a period. Actual availability depends on the configured source."],
    ["Connectivity", "Reachability", "Connectivity measurements can indicate whether a source or endpoint is reachable. Missing data should not be treated as a healthy result."],
  ],
  security: [
    ["Authentication events", "Local input", "Login events are processed inside the customer environment. Raw event content is not needed in the central dashboard."],
    ["Failed login count", "Approved summary", "Repeated failures can be summarized as an event count over a time window, without sending usernames or raw records."],
    ["Sensitive details", "Remain local", "Identifiers and other sensitive information are excluded by the local privacy pipeline before a payload is eligible for delivery."],
    ["Security signal", "Analysis input", "The SaaS can use approved event counts and categories to group related alerts and help an operator investigate."],
  ],
  apps: [
    ["Service metrics", "Application health", "Configured application sources may provide measurements that describe the health or performance of a service."],
    ["Service events", "Local event input", "Application events are processed locally. The central service receives only metadata permitted by the payload contract."],
    ["Source identity", "Pseudonymous ID", "A source ID links approved observations to the same monitored service without exposing its original identity."],
    ["Availability", "Source dependent", "Which application signals are available depends on the collector and the telemetry stream configured for the deployment."],
  ],
  collect: [
    ["Receive", "Read telemetry", "The collector reads the configured local sources and accepts the signals supported by its input adapter."],
    ["Normalize", "Common structure", "Measurements are converted into a consistent representation, including their source, event time and metric or event type."],
    ["Heartbeat", "Collector presence", "A heartbeat lets the platform track when a collector was last seen. Stale and offline state use configured timeouts."],
    ["Pass to privacy", "Local processing", "Collected information continues through filtering, aggregation and the policy gate before anything may leave the environment."],
  ],
  raw: [
    ["Original records", "Local only", "Raw telemetry remains inside the customer's environment. The SaaS metadata view is not a raw log viewer."],
    ["Sensitive values", "Local boundary", "Credentials, personal details and other sensitive raw fields should remain local and must not be included in approved payloads."],
    ["Local access", "Customer controlled", "Operators investigate original records through the collector's local tools and access controls, when available."],
    ["Central platform", "No raw records", "The central platform is designed to work from approved metadata and summaries, not copies of the raw source data."],
  ],
  redact: [
    ["Filter fields", "Remove unnecessary data", "The pipeline keeps information needed for supported monitoring and drops fields that are not approved for sharing."],
    ["Scrub secrets", "Defense in depth", "Known sensitive patterns are removed before payload construction. Scrubbing alone cannot guarantee arbitrary text is safe."],
    ["Pseudonymize", "Hide source identity", "Local source identifiers can be replaced with pseudonymous identifiers so observations remain linkable without sharing original names."],
    ["Policy check", "Final boundary", "The payload must still pass the allow-list and schema checks before it can be sent."],
  ],
  aggregate: [
    ["Time windows", "Group observations", "The collector groups local observations into defined windows. Window duration is part of the payload context."],
    ["Metric summary", "Derived value", "Instead of forwarding all raw readings, the pipeline can provide an approved aggregate or measured value."],
    ["Event count", "Summarized activity", "Events such as failed logins can be represented as a count and category without sending original event contents."],
    ["Event time", "UTC timestamp", "The event timestamp helps the platform order observations and calculate elapsed time. Late events need careful handling."],
  ],
  policy: [
    ["Allow-list", "Permitted fields", "The payload contract identifies which fields may be sent to the SaaS. Fields outside the approved structure are rejected."],
    ["Identity fields", "Scoped metadata", "Tenant, collector, source and region fields associate the observation with its authorized context."],
    ["Metric or event", "Approved summary", "A payload includes a supported metric or event summary, rather than unrestricted raw log text."],
    ["Validate", "Before delivery", "The collector checks the outgoing payload against its policy. The SaaS validates the contract again when it receives it."],
  ],
  outbox: [
    ["Queue", "Local persistence", "Approved payloads wait in the local outbox until they can be delivered to the platform."],
    ["Retry", "Recover connectivity", "If delivery fails, the collector can retry buffered payloads when the connection returns."],
    ["Payload ID", "Deduplication key", "A stable payload ID lets the receiver recognize repeated delivery attempts and avoid counting the same payload twice."],
    ["Acknowledgement", "Delivery result", "The local sender uses the SaaS response to decide what was accepted, duplicated or needs attention."],
  ],
  ingest: [
    ["Authenticate", "Collector identity", "The platform verifies the collector's credentials and checks that the identity matches the submitted tenant, collector and region."],
    ["Verify signature", "Payload integrity", "An HMAC signature is checked against the received request bytes to authenticate the sending collector and protect integrity."],
    ["Validate schema", "Metadata contract", "The SaaS validates each payload against the allowed fields and rejects invalid or unauthorized data."],
    ["Accept or deduplicate", "Delivery result", "New payload IDs are stored once. Repeated payloads are identified so retries do not create duplicate observations."],
  ],
  store: [
    ["Observation", "Approved metadata", "Validated metric and event summaries are stored with their payload IDs and timestamps."],
    ["Tenant isolation", "Scoped access", "Dashboard requests use the authenticated tenant context. Database row-level controls restrict access to that tenant's records."],
    ["Deduplication", "Stable identity", "Payload IDs help distinguish a new observation from a repeated delivery attempt within a tenant."],
    ["Linked evidence", "Incident lineage", "Retained payload references connect observations to related incidents and recommendations."],
  ],
  aiops: [
    ["Baseline", "Learn recent behavior", "The detector compares a metric with recent observations when enough baseline data is available."],
    ["Threshold fallback", "Critical values", "Configured critical thresholds can identify high-risk metric values even when a baseline is not ready."],
    ["Persistence", "Reduce noise", "The configured number of consecutive anomalous windows helps reduce alerts caused by brief fluctuations."],
    ["Correlation", "Group signals", "Related signals from a source and time window can be grouped into an incident. Correlation does not prove root cause."],
  ],
  health: [
    ["Excellent & Good", "Healthy states", "The platform derives health from reported signals and configured metric thresholds. The Health History page shows the current rules."],
    ["Fair & Poor", "Needs attention", "Elevated signals or stale heartbeats can cause a degraded state. The dashboard should explain the relevant signal or timeout."],
    ["Heartbeat age", "Freshness", "A collector becomes stale or offline according to configured timeouts measured from its last heartbeat."],
    ["History", "State transitions", "The platform records state changes with timestamps and reasons so an operator can review how health changed."],
  ],
  incident: [
    ["Related alerts", "Grouped signals", "The platform groups related alerts by source and time window into an incident, reducing repeated notifications."],
    ["Evidence", "Payload references", "Each incident can link to retained metadata payload IDs and contributing signals for investigation."],
    ["Severity", "Prioritization", "Incident severity helps operators prioritize investigation; it is based on the detected signals, not a guarantee of impact."],
    ["Lineage", "Trace the path", "The Incident lineage view shows actual links returned by the connected platform when incident data is available."],
  ],
  recommend: [
    ["Contributing signals", "Why it was flagged", "Recommendations refer to the signals and detection methods associated with the incident."],
    ["Suggested investigation", "Operator guidance", "The platform can suggest a next step for the operator to check, based on the available evidence."],
    ["Confidence", "Heuristic assessment", "A confidence label describes the recommendation's heuristic strength; it is not proof of the underlying cause."],
    ["Review", "Human decision", "An operator reviews the evidence and decides whether a follow-up action is appropriate."],
  ],
  action: [
    ["Propose", "Choose a simulation", "An operator can propose an available action against an incident in the action workspace."],
    ["Review", "Operator approval", "A proposed action can be approved or rejected through the platform's review workflow."],
    ["Audit", "Recorded transitions", "Action proposals and state changes are recorded so operators can review the decision history."],
    ["Simulated only", "No execution", "The current action workflow is a simulation. It does not execute commands or modify infrastructure."],
  ],
};

