"""The heartbeat carries real resource usage and a real configuration fingerprint (E21)."""
import asyncio
import json

import httpx

from collector.config import Config
from collector.outbox import LocalStore
from collector.sender import Sender, config_hash
from saas.schema import Heartbeat


def make(tmp_path, **kw):
    cfg = Config(data_dir=tmp_path, host_telemetry=False, **kw)
    return Sender(cfg, LocalStore(":memory:")), cfg


def test_the_hash_changes_when_a_setting_changes_and_is_stable_otherwise(tmp_path, monkeypatch):
    monkeypatch.delenv("PROFILE", raising=False)
    a = config_hash(Config(data_dir=tmp_path, window_s=5))
    assert a == config_hash(Config(data_dir=tmp_path, window_s=5)) and a.startswith("cfg-")
    assert a != config_hash(Config(data_dir=tmp_path, window_s=7))


def test_the_hash_changes_when_the_policy_or_mapping_file_changes(tmp_path, monkeypatch):
    policy = tmp_path / "policy.yaml"
    policy.write_text(Config(data_dir=tmp_path).policy_file.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = Config(data_dir=tmp_path, policy_file=policy)
    before = config_hash(cfg)
    policy.write_text(policy.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert config_hash(cfg) != before


def test_the_hash_does_not_depend_on_secrets(tmp_path):
    assert config_hash(Config(data_dir=tmp_path, collector_secret="one")) == config_hash(Config(data_dir=tmp_path, collector_secret="two"))


def test_the_heartbeat_has_resource_usage_and_passes_the_platforms_contract(tmp_path):
    sender, cfg = make(tmp_path)
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            await sender.heartbeat_once(c)

    asyncio.run(go())
    hb = seen[0]
    assert hb["config_hash"] == sender.config_hash != "dev"
    assert {"cpu_percent", "memory_percent", "disk_percent"} <= set(hb["resource_usage"])
    Heartbeat(**hb)  # the platform's own model accepts it (unknown field names would raise)
