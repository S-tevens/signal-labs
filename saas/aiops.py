from statistics import median
ALIASES={'cpu_pct':'cpu','memory_pct':'memory','mem_pct':'memory','disk_pct':'disk','packet_loss_pct':'packet_loss','cpu_percent':'cpu','cpu_usage':'cpu','memory_percent':'memory','memory_usage':'memory','disk_percent':'disk','disk_usage':'disk','latency_ms':'latency','network_latency':'latency','network_latency_ms':'latency','packet_loss_percent':'packet_loss','bandwidth_mbps':'bandwidth','service_availability':'availability'}
def canonical(name):
    name=name.lower().replace('.','_').replace('-','_'); return ALIASES.get(name,name)
def detect(metric, history, config):
    name=canonical(metric['name']); value=metric['value']; rule=config['metrics'].get(name,{})
    if len(history)<config['baseline_min']: return None
    center=median(history); mad=median(abs(x-center) for x in history); scale=max(1.4826*mad,rule.get('floor',max(abs(center)*0.02,0.01)))
    z=(value-center)/scale
    if abs(z)<config['anomaly_z']: return None
    if rule.get('inverse') and z>0: return None
    return {'signal':name,'value':value,'baseline':round(center,4),'robust_z':round(z,3),'samples':len(history),'why':f'{name} is {abs(z):.1f} robust deviations from its rolling median ({center:.2f})','severity':'critical' if abs(z)>=8 else 'warning','method':'rolling median/MAD'}
def recommendation(signals):
    names={s['signal'] for s in signals}
    if 'failed_login' in names: cause='Possible authentication attack'; action='Review local authentication records and verify account access.'
    elif names & {'latency','packet_loss','connectivity','bandwidth'}: cause='Possible network degradation'; action='Check local interface errors, link saturation and routing; verify dependencies.'
    elif names & {'cpu','memory','disk'}: cause='Possible resource pressure'; action='Inspect local resource-heavy processes and capacity before any restart.'
    else: cause='Unusual telemetry pattern'; action='Inspect the local source and compare recent changes.'
    return {'likely_cause':cause,'action':action,'confidence':'medium' if len(names)>1 else 'low','confidence_type':'heuristic, not a calibrated probability','why':'; '.join(s['why'] for s in signals)}
