import time
from pathlib import Path
import yaml,pytest
from pydantic import ValidationError
from saas.aiops import detect,canonical,recommendation
from saas.health import metric_state,worse
from saas.schema import Payload
from saas.store import utc,epoch
from saas.proof import p95
from saas.tests.test_service import p
CONFIG=yaml.safe_load((Path(__file__).parents[1]/'config/thresholds.yaml').read_text())
def test_baseline():
    assert detect({'name':'cpu_pct','value':20},[20]*8,CONFIG) is None
    r=detect({'name':'cpu_pct','value':50},[20]*8,CONFIG)
    assert r['method']=='rolling median/MAD' and r['robust_z']==10
    assert detect({'name':'cpu','value':50},[20]*3,CONFIG) is None
def test_states():
    assert [metric_state({'name':'cpu_pct','value':v},CONFIG) for v in [20,65,85,98]]==['Excellent','Good','Fair','Poor']
    assert worse('Excellent','Fair')=='Fair'
def test_schema():
    Payload.model_validate(p())
    with pytest.raises(ValidationError): Payload.model_validate({**p(),'raw_log':'secret'})
    with pytest.raises(ValidationError): Payload.model_validate({**p(),'event_ts_utc':'2026-01-01T00:00:00'})
def test_utc():
    t=time.time();assert abs(epoch(utc(t))-t)<.001
    with pytest.raises(ValueError): epoch('2026-01-01T00:00:00')
def test_p95():
    assert p95([]) is None and p95(list(range(1,101)))==95
    assert p95([1,2,3])==3
def test_recommendation():
    r=recommendation([{'signal':'cpu','why':'CPU increased'},{'signal':'memory','why':'Memory increased'}]);assert r['confidence']=='medium' and 'resource pressure' in r['likely_cause']
def test_schema_rls_migration_declarations():
    ddl=(Path(__file__).parents[1]/'migrations/001.sql').read_text()
    assert 'PRIMARY KEY(tenant_id,id)' in ddl and 'FORCE ROW LEVEL SECURITY' in ddl and 'WITH CHECK' in ddl
