# Verification

Local command: `python -m pytest -q saas/tests`
Result: **7 passed, 10 skipped**. Python compile check passed.

Skipped tests require a dedicated migrated PostgreSQL test database (see README). No live DB, Docker, load balancer, or organizer stream was available in this execution environment. No throughput/latency numbers or zero-loss claims have been fabricated. The integration tests in the package are ready to run after migration.
