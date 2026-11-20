"""The committed contract must match collector/schema.py. Fails if the schema drifts."""
import json

from collector.export_schema import CONTRACT_PATH, build_schema


def test_contract_matches_schema():
    committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert committed == build_schema(), (
        "collector/schema.py changed but contracts/payload.schema.json was not regenerated. "
        "Run `python -m collector.export_schema` and get the change approved by the SaaS owner."
    )
