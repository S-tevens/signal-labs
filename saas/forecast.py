"""Short, validated linear projections; descriptive evidence, not an alert."""
from math import isfinite
from .store import epoch,utc
from .aiops import canonical


def project(rows, name, config, now, horizon_s=60):
    points=[]
    for row in rows:
        try:
            t=epoch(row['ts']); v=float(row['value'])
            if isfinite(t) and isfinite(v): points.append((t,v))
        except (ValueError, TypeError, KeyError): continue
    points=sorted(dict(points).items())
    unavailable=lambda reason: {'available':False,'reason':reason,'sample_count':len(points)}
    if len(points)<8: return unavailable('At least 8 distinct recent observations are required.')
    if now-points[-1][0]>120 or points[-1][0]>now+5: return unavailable('Latest observation is stale or in the future.')
    span=points[-1][0]-points[0][0]
    if span<60: return unavailable('Observations must span at least 60 seconds.')
    train=points[:-2]; holdout=points[-2:]
    x0=train[0][0]; xs=[t-x0 for t,_ in train]; ys=[v for _,v in train]
    mx=sum(xs)/len(xs); my=sum(ys)/len(ys); denom=sum((x-mx)**2 for x in xs)
    if denom<=0: return unavailable('Observation timestamps do not span a usable interval.')
    slope=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/denom
    fit=lambda t: my+slope*(t-x0-mx)
    linear_error=sum(abs(fit(t)-v) for t,v in holdout)/len(holdout)
    baseline_error=sum(abs(train[-1][1]-v) for _,v in holdout)/len(holdout)
    if linear_error > baseline_error+1e-9: return unavailable('Linear trend did not outperform the last-value baseline on the two most recent observations.')
    horizon=min(max(1,int(horizon_s)),300,int(span)); predicted=points[-1][1]+slope*horizon
    if canonical(name) in {'cpu','memory','disk','packet_loss'}: predicted=max(0,min(100,predicted))
    else: predicted=max(0,predicted)
    rule=config['metrics'].get(canonical(name),{}); threshold=rule.get('poor'); inverse=bool(rule.get('inverse'))
    crossing=threshold is not None and (predicted<=threshold if inverse else predicted>=threshold)
    return {'available':True,'metric':canonical(name),'latest':points[-1][1],'latest_event_ts_utc':utc(points[-1][0]),'horizon_s':horizon,'projected':round(predicted,2),'slope_per_min':round(slope*60,3),'sample_count':len(points),'sample_span_s':round(span,1),'holdout_mae':round(linear_error,3),'last_value_mae':round(baseline_error,3),'poor_threshold':threshold,'comparison':'<=' if inverse else '>=','projected_threshold_crossing':crossing,'method':'linear least squares; last two observations held out','note':'Experimental projection, not a prediction guarantee or alert. No model confidence interval is provided.'}
