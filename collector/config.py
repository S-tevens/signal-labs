from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

COLLECTOR_VERSION = "0.1.0"
DEV_COLLECTOR_KEY = "key-acme-1"  # the built-in development credential; an enrolled collector never uses it


@dataclass
class Config:
    collector_id: str = field(default_factory=lambda: os.getenv("COLLECTOR_ID", "col-blr-01"))
    tenant_ref: str = field(default_factory=lambda: os.getenv("TENANT_REF", "t-acme"))
    region: str = field(default_factory=lambda: os.getenv("REGION", "in"))
    collector_key: str = field(default_factory=lambda: os.getenv("COLLECTOR_KEY", DEV_COLLECTOR_KEY))
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
    # The /local/* views show raw records with secrets. They answer only requests from this machine unless
    # this is set (then put your own authentication in front; never expose them to the internet).
    local_allow_remote: bool = field(default_factory=lambda: os.getenv("LOCAL_ALLOW_REMOTE", "0") == "1")
    # Transport security (E3).
    saas_ca_file: str = field(default_factory=lambda: os.getenv("SAAS_CA_FILE", ""))  # CA that signed the SaaS cert
    require_tls: bool = field(default_factory=lambda: os.getenv("REQUIRE_TLS", "0") == "1")
    batch_size: int = 50
    # Where this collector's identity came from: "enrolled" (credentials.json from the platform) or "environment".
    credentials_source: str = field(default="environment", init=False)
    enrolled_at: str = field(default="", init=False)

    def __post_init__(self) -> None:
        """Use enrolled credentials when this collector has them.

        An explicit COLLECTOR_KEY in the environment wins (an operator override). Otherwise the identity, signing
        secret, pseudonym secret and platform URL come from <data_dir>/credentials.json, so an enrolled collector never
        runs on the built-in development defaults. A damaged credentials file raises instead of being ignored.
        """
        if str(self.data_dir) == ":memory:" or os.getenv("COLLECTOR_KEY"):
            return
        from . import credentials

        creds = credentials.load(self.data_dir)
        if creds is None:
            return
        self.collector_id, self.tenant_ref, self.region = creds["collector_id"], creds["tenant_ref"], creds["region"]
        self.collector_key, self.collector_secret = creds["collector_key"], creds["collector_secret"]
        if not os.getenv("PSEUDO_SECRET"):
            self.pseudo_secret = creds["pseudo_secret"]
        if not os.getenv("SAAS_URL"):
            self.saas_url = creds["saas_url"]
        self.credentials_source = "enrolled"
        self.enrolled_at = creds.get("enrolled_at", "")
    raw_retention_s: int = field(default_factory=lambda: int(os.getenv("RAW_RETENTION_S", "86400")))  # raw records: 1 day
    # Limits (E7). Caps are enforced as data is written, so a flood cannot outrun the retention timer.
    outbox_retention_s: int = field(default_factory=lambda: int(os.getenv("OUTBOX_RETENTION_S", "604800")))  # transfer record: 7 days
    retention_interval_s: float = field(default_factory=lambda: float(os.getenv("RETENTION_INTERVAL_S", "300")))
    raw_max_rows: int = field(default_factory=lambda: int(os.getenv("RAW_MAX_ROWS", "500000")))
    outbox_max_pending: int = field(default_factory=lambda: int(os.getenv("OUTBOX_MAX_PENDING", "100000")))
    max_db_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_DB_BYTES", str(1 << 30))))  # live data, 1 GiB
    max_line_chars: int = field(default_factory=lambda: int(os.getenv("MAX_LINE_CHARS", "65536")))
    max_ingest_bytes: int = field(default_factory=lambda: int(os.getenv("MAX_INGEST_BYTES", str(8 << 20))))  # one request, 8 MiB
