"""Both consumers must honor the frozen edge schema and known semantic checks."""
import json
from datetime import datetime, timezone
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from collector.schema import Payload as EdgePayload
from collector.export_schema import build_schema
from saas.contract import SCHEMA, validate_contract
from saas.schema import Payload as SaasPayload

BASE = {'payload_id':'12345678-1234-1234-1234-123456789abc','tenant_ref':'t-acme','collector_id':'col-blr-01','source_id':'src_12345678','region':'in','event_ts_utc':datetime.now(timezone.utc).isoformat(),'source_tz':'Asia/Kolkata','window_s':5,'metric':{'name':'cpu_pct','value':32.0,'unit':'%'},'health_state':'Excellent','collector_version':'1.0.0'}

def test_edge_to_saas_and_frozen_schema():
    assert SCHEMA == build_schema()
    payload=EdgePayload.model_validate(BASE).model_dump(mode='json',exclude_none=True)
    assert validate_contract(payload)==payload
    assert SaasPayload.model_validate(payload)

def test_saas_rejects_schema_forbidden_and_semantically_invalid():
    for payload in [{**BASE,'source_id':'internal-server'}, {**BASE,'payload_id':'plain-id'}, {**BASE,'metric':{'name':'anything','value':1,'unit':'%'}}, {**BASE,'raw':'secret'}]:
        with pytest.raises(HTTPException): validate_contract(payload)
    mismatch={**BASE,'metric':{'name':'cpu_pct','value':32.0,'unit':'ms'}}
    with pytest.raises(ValidationError): EdgePayload.model_validate(mismatch)
    with pytest.raises(ValidationError): SaasPayload.model_validate(validate_contract(mismatch))


def test_actual_edge_aggregates_pass_the_full_saas_contract():
    from collector.config import Config
    from collector.outbox import LocalStore
    from collector.pipeline import Pipeline
    store = LocalStore(':memory:')
    pipeline = Pipeline(Config(data_dir=':memory:'), store)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    entries = [json.dumps({'kind':'metric','ts':now,'tz':'Asia/Kolkata','host':'web-1','name':'cpu_pct','value':30}),
               f'ts={now} host=router-1 metric=latency_ms value=120.5',
               'Nov 20 09:15:01 web-1 sshd[88]: Failed password for root from 10.2.4.7']
    for line in entries:
        assert pipeline.process(line)['status'] == 'aggregated'
    pipeline.flush(force=True)
    outgoing = store.pending(50)
    assert outgoing
    for payload in outgoing:
        assert SaasPayload.model_validate(validate_contract(payload))
