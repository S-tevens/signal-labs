import test from 'node:test';
import assert from 'node:assert/strict';
import { incidentTimeline } from '../src/incidentEvidence.js';

test('timeline orders recorded timestamps and links both events to the payload', () => {
  const signals=[{signal:'cpu',value:97,unit:'%',payload_id:'p1',event_ts_utc:'2026-01-01T00:00:02Z',alert_ts_utc:'2026-01-01T00:00:04Z',method:'threshold'}, {signal:'latency',payload_id:'p2',event_ts_utc:'2026-01-01T00:00:01Z'}];
  const result=incidentTimeline(signals);
  assert.deepEqual(result.map(e=>e.key),['1-event','0-event','0-alert']);
  assert.equal(result[2].payloadId,'p1'); assert.equal(result[2].method,'threshold');
});
test('missing or invalid timestamps do not produce fabricated timeline events', () => {
  assert.deepEqual(incidentTimeline([{event_ts_utc:'invalid'},{}]),[]);
  assert.deepEqual(incidentTimeline(null),[]);
});
