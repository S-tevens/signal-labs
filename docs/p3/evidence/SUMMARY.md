# Measurement summary

One machine, live timestamps, one run per row (see [README.md](README.md) for how to read them). Each row links to its full evidence file.

| Run (UTC) | Collector timing | Collection to dashboard p95 (strict) | Alert, hard threshold (99% CPU) | Alert, deviation from baseline (70% CPU) | Offline to Poor (from last heartbeat) | Zero loss through a 15 s outage |
|---|---|---|---|---|---|---|
| [15:40:51](measure-20261120T154051Z.md) | `default` (5 s window, 2 s grace) | **10.18 s FAIL** (n=30; latency only) | n/a | n/a | n/a | n/a |
| [15:42:11](measure-20261120T154211Z.md) | `default` | **11.07 s FAIL** (n=39) | 4.38 s PASS | n/a | **60.16 s FAIL** | PASS: 74 created, 0 missing, 0 duplicates, replay 5.5 s |
| [15:47:25](measure-20261120T154725Z.md) | `realtime` (2 s window, 1 s grace) | **5.95 s PASS** (n=90) | 3.58 s PASS | n/a | n/a | PASS: 136 created, 0 missing, 0 duplicates, replay 5.8 s |
| [15:51:07](measure-20261120T155107Z.md) | `realtime` | n/a | n/a | 6.58 s PASS | **60.28 s FAIL** | n/a |

## What this shows

1. **The default timing misses the dashboard target** under the strict reading (clock starts at the earliest record the window could hold). Two runs gave 10.18 s and 11.07 s. A window of 5 s plus a grace of 2 s is already a 7 s floor before any delivery delay.
2. **The `realtime` profile fixes it with real margin**: 5.95 s against a 10 s target, at the cost of roughly 2.5 times more payloads per collector.
3. **Alerts are fast**: 3.6 to 4.4 s for a hard threshold breach and 6.6 s for a deviation from baseline, well inside 15 s. An earlier written estimate of 10 to 14 s was wrong; it assumed the persistence rule delayed every alert, but a hard threshold breach is alerted without it.
4. **Offline detection misses by about 0.2 s, reproducibly** (60.16 s, then 60.28 s). The platform marks a collector Poor exactly 60 s after its last heartbeat, so it cannot meet "within 60 s" by design. The fix is a platform setting: lower `offline_after_s` (task P17). Poor appears about 0.2 to 0.3 s after the configured threshold, so a threshold of 40 s should give about 40 s.
5. **Delivery is sound**: nothing lost and nothing duplicated through an outage, with the buffered backlog delivered within about 6 s of reconnecting.

## Caveats

- Each row is one run on one machine with 30 to 90 payloads. The two `default` runs differ by about 1 s, so treat margins under a second as noise, and repeat a run before quoting a number.
- The hard-threshold and deviation tests inject a single metric on a unique host. A real stream with many sources may behave differently.
- The platform's own `stored_duplicates` figure is a constant 0 in its code, so duplicates are checked here independently: by looking for repeated payload IDs in the platform's listing, and by counting duplicate attempts it rejected.
