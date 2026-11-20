from .aiops import canonical
RANK={'Excellent':0,'Good':1,'Fair':2,'Poor':3}
def metric_state(metric,config):
    r=config['metrics'].get(canonical(metric['name']),{}); v=metric['value']
    if 'poor' not in r: return 'Excellent'
    if r.get('inverse'):
        return 'Poor' if v<=r['poor'] else 'Fair' if v<=r['fair'] else 'Good' if v<r['good'] else 'Excellent'
    return 'Poor' if v>=r['poor'] else 'Fair' if v>=r['fair'] else 'Good' if v>=r['good'] else 'Excellent'
def worse(*states): return max(states,key=RANK.get)
