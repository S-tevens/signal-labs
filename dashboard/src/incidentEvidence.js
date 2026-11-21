// Timeline entries come only from timestamps retained in the incident.
export function incidentTimeline(signals) {
  const entries=[];
  for (const [index, signal] of (signals || []).entries()) {
    const label=(signal.signal || 'Unknown signal').replaceAll('_',' ');
    if (signal.event_ts_utc && Number.isFinite(Date.parse(signal.event_ts_utc)))
      entries.push({ key:`${index}-event`, time:signal.event_ts_utc, type:'Observation', label, payloadId:signal.payload_id, value:signal.value, unit:signal.unit });
    if (signal.alert_ts_utc && Number.isFinite(Date.parse(signal.alert_ts_utc)))
      entries.push({ key:`${index}-alert`, time:signal.alert_ts_utc, type:'Alert raised', label, payloadId:signal.payload_id, method:signal.method });
  }
  return entries.sort((a,b) => Date.parse(a.time)-Date.parse(b.time));
}
