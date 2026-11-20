"""Validate the immutable edge/SaaS wire contract before ingesting anything."""
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from fastapi import HTTPException

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'contracts' / 'payload.schema.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())

def validate_contract(value):
    if not isinstance(value, dict) or not VALIDATOR.is_valid(value):
        raise HTTPException(422, 'Payload does not match frozen metadata contract')
    # JSON Schema's nullable properties and oneOf do not by themselves guarantee
    # an object body. The wire contract requires exactly one non-null body.
    if (value.get('metric') is None) == (value.get('event') is None):
        raise HTTPException(422, 'Exactly one metadata body is required')
    if 'metric' in value and value['metric'] is None or 'event' in value and value['event'] is None:
        raise HTTPException(422, 'Omit the unused metadata body')
    return value
