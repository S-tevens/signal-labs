"""Generate contracts/payload.schema.json from collector/schema.py.

Run from the repo root:  python -m collector.export_schema
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import SCHEMA_VERSION, Payload

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "payload.schema.json"


def build_schema() -> dict:
    schema = Payload.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "EgressPayload"
    schema["x-schema-version"] = SCHEMA_VERSION
    # Exactly one body. Producers must omit absent fields (exclude_none).
    schema["oneOf"] = [{"required": ["metric"]}, {"required": ["event"]}]
    return schema


def main() -> None:
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(build_schema(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {CONTRACT_PATH}")


if __name__ == "__main__":
    main()
