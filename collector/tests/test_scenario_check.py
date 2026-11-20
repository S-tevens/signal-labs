"""The scenario check's judging logic (E28): missed, extra, false alarms, grouping and delay."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("scenario_check", Path(__file__).resolve().parents[2] / "simulator" / "scenario_check.py")
sc = importlib.util.module_from_spec(_spec)
sys.modules["scenario_check"] = sc
_spec.loader.exec_module(sc)

T = 1_800_000_000.0


def iso(e):
    return sc.sc.iso(e)


def sig(name, at, delay=3.0, method="rolling median/MAD"):
    return {"signal": name, "event_ts_utc": iso(at), "alert_ts_utc": iso(at + delay), "method": method}


def inc(source, signals, iid="i1"):
    return {"id": iid, "source_id": source, "signals": signals, "alert_count": len(signals)}


def test_a_correct_detection_passes_with_its_delay():
    r = sc.evaluate("cpu-spike", {"cpu"}, False, "s", [inc("s", [sig("cpu", T + 1)])], T)
    assert r["verdict"] == "PASS" and r["missed"] == [] and r["extra"] == [] and r["first_alert_s"] == 4.0


def test_a_missed_signal_fails():
    r = sc.evaluate("storm", {"cpu", "latency"}, True, "s", [inc("s", [sig("cpu", T + 1)])], T)
    assert r["verdict"] == "FAIL" and r["missed"] == ["latency"] and r["all_expected_alerts_s"] is None


def test_an_unexpected_extra_signal_fails():
    r = sc.evaluate("cpu-spike", {"cpu"}, False, "s", [inc("s", [sig("cpu", T + 1), sig("memory", T + 2)])], T)
    assert r["verdict"] == "FAIL" and r["extra"] == ["memory"]


def test_a_slow_alert_fails_the_15_second_target():
    r = sc.evaluate("cpu-spike", {"cpu"}, False, "s", [inc("s", [sig("cpu", T + 1, delay=16.0)])], T)
    assert r["verdict"] == "FAIL"


def test_a_signal_before_the_injection_is_a_false_alarm_and_fails():
    r = sc.evaluate("cpu-spike", {"cpu"}, False, "s", [inc("s", [sig("cpu", T - 30), sig("cpu", T + 1)])], T)
    assert r["false_alarms_before_injection"] == 1 and r["verdict"] == "FAIL"


def test_a_storm_must_be_one_incident():
    two = [inc("s", [sig("cpu", T + 1)], "a"), inc("s", [sig("latency", T + 1)], "b")]
    assert sc.evaluate("storm", {"cpu", "latency"}, True, "s", two, T)["verdict"] == "FAIL"
    one = [inc("s", [sig("cpu", T + 1), sig("latency", T + 2)])]
    r = sc.evaluate("storm", {"cpu", "latency"}, True, "s", one, T)
    assert r["verdict"] == "PASS" and r["incidents"] == 1 and r["alerts_in_those_incidents"] == 2


def test_other_sources_are_ignored_and_decoy_alerts_count_as_false_alarms():
    incidents = [inc("other", [sig("cpu", T + 1)]), inc("decoy", [sig("bandwidth", T + 5), sig("cpu", T + 6)], "d")]
    assert sc.evaluate("cpu-spike", {"cpu"}, False, "s", incidents, T)["verdict"] == "FAIL"  # nothing on its own source: missed
    fa = sc.false_alarms(["decoy"], incidents)
    assert fa == {"incidents": 1, "alerts": 2, "signals": ["bandwidth", "cpu"]}
