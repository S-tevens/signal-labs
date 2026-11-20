import pytest
from fastapi.testclient import TestClient

from collector.config import PROFILES, Config
from collector.main import create_app

TIMING_ENV = ("WINDOW_S", "GRACE_S", "FLUSH_INTERVAL_S", "SEND_INTERVAL_S", "HEARTBEAT_INTERVAL_S", "PROFILE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in TIMING_ENV:
        monkeypatch.delenv(name, raising=False)


def timing(cfg):
    return (cfg.window_s, cfg.grace_s, cfg.flush_interval_s, cfg.send_interval_s, cfg.heartbeat_interval_s)


def test_default_profile_keeps_the_documented_timing():
    cfg = Config(data_dir=":memory:")
    assert cfg.profile == "default" and timing(cfg) == (5, 2.0, 1.0, 1.0, 10.0)


def test_realtime_profile_shortens_every_stage_of_the_path():
    import os

    os.environ["PROFILE"] = "realtime"
    cfg = Config(data_dir=":memory:")
    assert cfg.profile == "realtime" and timing(cfg) == (2, 1.0, 0.5, 0.25, 5.0)
    # the floor under the strict latency measurement is window + grace
    assert cfg.window_s + cfg.grace_s < 5 + 2


def test_an_explicit_setting_always_wins_over_the_profile(monkeypatch):
    monkeypatch.setenv("PROFILE", "realtime")
    monkeypatch.setenv("WINDOW_S", "3")
    monkeypatch.setenv("SEND_INTERVAL_S", "0.5")
    cfg = Config(data_dir=":memory:")
    assert cfg.window_s == 3 and cfg.send_interval_s == 0.5
    assert cfg.grace_s == 1.0  # untouched settings still come from the profile


def test_unknown_profile_fails_loudly_instead_of_silently_using_defaults(monkeypatch):
    monkeypatch.setenv("PROFILE", "turbo")
    with pytest.raises(ValueError, match="unknown PROFILE"):
        Config(data_dir=":memory:")


def test_profile_names_are_case_insensitive_and_blank_means_default(monkeypatch):
    monkeypatch.setenv("PROFILE", "  REALTIME ")
    assert Config(data_dir=":memory:").profile == "realtime"
    monkeypatch.setenv("PROFILE", "")
    assert Config(data_dir=":memory:").profile == "default"


def test_the_timing_endpoint_reports_the_profile_in_use(monkeypatch):
    monkeypatch.setenv("PROFILE", "realtime")
    app = create_app(Config(data_dir=":memory:", host_telemetry=False), run_sender=False)
    body = TestClient(app).get("/local/timing").json()
    assert body["profile"] == "realtime" and body["window_s"] == 2 and body["send_interval_s"] == 0.25


def test_every_profile_only_sets_settings_the_config_actually_reads():
    known = {"WINDOW_S", "GRACE_S", "FLUSH_INTERVAL_S", "SEND_INTERVAL_S", "HEARTBEAT_INTERVAL_S"}
    for name, values in PROFILES.items():
        assert set(values) <= known, name
