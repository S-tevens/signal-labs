from saas.forecast import project
from saas.store import utc
CONFIG={'metrics':{'cpu':{'poor':95}}}

def rows(values, step=15):
    return [{'ts':utc(1000+i*step),'value':v} for i,v in reversed(list(enumerate(values)))]

def test_forecast_validates_and_projects_recent_linear_series():
    result=project(rows([40,42,44,46,48,50,52,54]),'cpu_pct',CONFIG,1105,60)
    assert result['available'] and result['sample_count']==8
    assert result['projected']==62 and result['holdout_mae'] < result['last_value_mae']
    assert not result['projected_threshold_crossing']

def test_forecast_refuses_insufficient_stale_or_bad_fit():
    assert not project(rows([1,2]),'cpu_pct',CONFIG,1015)['available']
    assert 'stale' in project(rows([40,42,44,46,48,50,52,54]),'cpu_pct',CONFIG,2000)['reason']
    assert 'baseline' in project(rows([10,20,30,40,50,60,10,10]),'cpu_pct',CONFIG,1105)['reason']

def test_forecast_horizon_is_bounded_and_values_are_valid():
    result=project(rows([80,82,84,86,88,90,92,94]),'cpu_pct',CONFIG,1105,300)
    assert result['available'] and result['horizon_s']==105 and result['projected']==100
    assert result['projected_threshold_crossing']
