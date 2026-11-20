from __future__ import annotations

import os
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
    batch_size: int = 50
    raw_retention_s: int = field(default_factory=lambda: int(os.getenv("RAW_RETENTION_S", "86400")))
