# Measurement summary

One machine, live timestamps, one run per row (see [README.md](README.md) for how to read them). Each row links to its full evidence file.

| Run (UTC) | Collector timing | Collection to dashboard p95 (strict) | Alert, hard threshold (99% CPU) | Alert, deviation from baseline (70% CPU) | Offline to Poor (from last heartbeat) | Zero loss through a 15 s outage |
|---|---|---|---|---|---|---|
| [15:40:51](measure-20261120T154051Z.md) | `default` (5 s window, 2 s grace) | **10.18 s FAIL** (n=30; latency only) | n/a | n/a | n/a | n/a |
| [15:42:11](measure-20261120T154211Z.md) | `default` | **11.07 s FAIL** (n=39) | 4.38 s PASS | n/a | **60.16 s FAIL** | PASS: 74 created, 0 missing, 0 duplicates, replay 5.5 s |
| [15:47:25](measure-20261120T154725Z.md) | `realtime` (2 s window, 1 s grace) | **5.95 s PASS** (n=90) | 3.58 s PASS | n/a | n/a | PASS: 136 created, 0 missing, 0 duplicates, replay 5.8 s |
| [15:51:07](measure-20261120T155107Z.md) | `realtime` | n/a | n/a | 6.58 s PASS | **60.28 s FAIL** | n/a |
| [18:30:17](measure-20261120T183017Z.md) | `realtime`, merged code, platform `offline_after_s: 40` | **6.13 s PASS** (n=90) | 5.70 s PASS | 6.24 s PASS | **40.26 s PASS** (from last heartbeat) | PASS: 133 created, 0 missing, 0 duplicates, replay 5.5 s |
| [19:23:23](measure-20261120T192323Z.md) | `realtime`, after the platform's push-update change merged | **6.01 s PASS** (n=90; latency only) | n/a | n/a | n/a | n/a |
| [19:31:02](measure-20261120T193102Z.md) (final rehearsal, [record](rehearsal-20261120T192509Z.md)) | `realtime`, merged build | **7.00 s PASS** (n=93) | 2.95 s PASS | 6.43 s PASS | **40.17 s PASS** | PASS: 137 created, 0 missing, 0 duplicates, replay 6.1 s |
| [20:47:11](measure-20261120T204711Z.md) ([rehearsal](rehearsal-20261120T203359Z.md)) | `realtime`, **current build**, dashboard dev server running, machine short of memory (about 770 MB free) | **15.49 s FAIL** (n=90) | 10.79 s PASS | 10.99 s PASS | 44.99 s PASS | PASS: 136 created, 0 missing, 0 duplicates, replay 37.95 s |
| [20:56:46](measure-20261120T205646Z.md) | `realtime`, **current build**, dashboard dev server stopped | **8.40 s PASS** (n=90) | 4.96 s PASS | 6.51 s PASS | **41.18 s PASS** | PASS: 137 created, 0 missing, 0 duplicates, replay 10.3 s |


**Which build each row measured.** The rows at 18:30, 19:23 and 19:31 UTC ran on a stack that had been started before the platform's push-update branch was merged: a restart step left the old processes running, so they describe the build before that merge, not after. The last two rows are the first runs on the current build. Under memory pressure and with the dashboard dev server running, the same measurement failed the dashboard target (15.49 s) and everything was slower, including a single idle ingest (about 1.2 s against 0.13 s once the dashboard was stopped). The cause is not isolated; the push-update design recomputes a dashboard snapshot per ingest while a stream is connected, which is the leading suspect. Treat 8 to 9 s as the honest dashboard figure on this machine and expect it to rise with a connected dashboard.
## What this shows

1. **The default timing misses the dashboard target** under the strict reading (clock starts at the earliest record the window could hold). Two runs gave 10.18 s and 11.07 s. A window of 5 s plus a grace of 2 s is already a 7 s floor before any delivery delay.
2. **The `realtime` profile fixes it with real margin**: 5.95 s against a 10 s target, at the cost of roughly 2.5 times more payloads per collector.
3. **Alerts are fast**: 3.6 to 4.4 s for a hard threshold breach and 6.6 s for a deviation from baseline, well inside 15 s. An earlier written estimate of 10 to 14 s was wrong; it assumed the persistence rule delayed every alert, but a hard threshold breach is alerted without it.
4. **Offline detection missed by about 0.2 s, reproducibly** (60.16 s, then 60.28 s) while the platform's threshold was 60 s. After the platform lowered `offline_after_s` to 40 (task P17), the latest run measured **40.26 s** from the last heartbeat, a margin of about 20 s, as predicted (Poor appears 0.2 to 0.3 s after the threshold).
5. **Delivery is sound**: nothing lost and nothing duplicated through an outage, with the buffered backlog delivered within about 6 s of reconnecting.

## Caveats

- Each row is one run on one machine with 30 to 90 payloads. The two `default` runs differ by about 1 s, so treat margins under a second as noise, and repeat a run before quoting a number.
- The hard-threshold and deviation tests inject a single metric on a unique host. A real stream with many sources may behave differently.
- The platform's own `stored_duplicates` figure is a constant 0 in its code, so duplicates are checked here independently: by looking for repeated payload IDs in the platform's listing, and by counting duplicate attempts it rejected.
