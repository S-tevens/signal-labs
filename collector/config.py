from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

COLLECTOR_VERSION = "0.1.0"


@dataclass
class Config:
    collector_id: str = field(default_factory=lambda: os.getenv("COLLECTOR_ID", "col-blr-01"))
    tenant_ref: str = field(default_factory=lambda: os.getenv("TENANT_REF", "t-acme"))
    region: str = field(default_factory=lambda: os.getenv("REGION", "in"))
    collector_key: str = field(default_factory=lambda: os.getenv("COLLECTOR_KEY", "key-acme-1"))
    collector_secret: str = field(default_factory=lambda: os.getenv("COLLECTOR_SECRET", "dev-secret-acme"))
    pseudo_secret: str = field(default_factory=lambda: os.getenv("PSEUDO_SECRET", "dev-local-pseudonym-secret"))
    saas_url: str = field(default_factory=lambda: os.getenv("SAAS_URL", "http://localhost:8080"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data/collector")))
    send_interval_s: float = field(default_factory=lambda: float(os.getenv("SEND_INTERVAL_S", "1")))
    heartbeat_interval_s: float = field(default_factory=lambda: float(os.getenv("HEARTBEAT_INTERVAL_S", "10")))
    # Local aggregation: records are grouped per source into fixed windows and sent as one summary.
    window_s: int = field(default_factory=lambda: int(os.getenv("WINDOW_S", "5")))
    grace_s: float = field(default_factory=lambda: float(os.getenv("GRACE_S", "2")))  # wait for late events
    flush_interval_s: float = field(default_factory=lambda: float(os.getenv("FLUSH_INTERVAL_S", "1")))
    burst_threshold: int = field(default_factory=lambda: int(os.getenv("BURST_THRESHOLD", "5")))  # failures per window
    policy_file: Path = field(
        default_factory=lambda: Path(os.getenv("POLICY_FILE", str(Path(__file__).with_name("policy.yaml"))))
    )
    # Real host telemetry (collector/sources/host.py).
    host_telemetry: bool = field(default_factory=lambda: os.getenv("HOST_TELEMETRY", "1") != "0")
    host_label: str = field(default_factory=lambda: os.getenv("HOST_LABEL", "") or socket.gethostname())
    host_interval_s: float = field(default_factory=lambda: float(os.getenv("HOST_INTERVAL_S", "2")))
    probe_interval_s: float = field(default_factory=lambda: float(os.getenv("PROBE_INTERVAL_S", "5")))
    probe_attempts: int = field(default_factory=lambda: int(os.getenv("PROBE_ATTEMPTS", "4")))
    probe_timeout_s: float = field(default_factory=lambda: float(os.getenv("PROBE_TIMEOUT_S", "1.0")))
    probe_targets: str = field(default_factory=lambda: os.getenv("PROBE_TARGETS", ""))  # "host:port,host:port"
    service_checks: str = field(default_factory=lambda: os.getenv("SERVICE_CHECKS", ""))  # "name=host:port,..."
    disk_paths: str = field(default_factory=lambda: os.getenv("DISK_PATHS", ""))  # default: the system drive or /
    source_tz: str = field(default_factory=lambda: os.getenv("SOURCE_TZ", "UTC"))  # IANA name, e.g. Asia/Kolkata
    # Transport security (E3).
    saas_ca_file: str = field(default_factory=lambda: os.getenv("SAAS_CA_FILE", ""))  # CA that signed the SaaS cert
    require_tls: bool = field(default_factory=lambda: os.getenv("REQUIRE_TLS", "0") == "1")
    batch_size: int = 50
    raw_retention_s: int = field(default_factory=lambda: int(os.getenv("RAW_RETENTION_S", "86400")))
