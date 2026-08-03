# Routing Test Execution Notes

## 2026-08-03 Ticket 13 real-graph verification deferrals

- Local self-hosted OSRM smoke testing exercised the frozen representative corpus with normal,
  `motorway`, `toll`, and `motorway,toll` exclusions. Candidate counts and response timing are
  recorded in `docs/CORRIDOR_MATCHER_BENCHMARK.md`.
- The national PostGIS corridor-risk version was unavailable to that local OSRM container, so
  coverage and matcher timing for restricted-route geometries were not measured. This is a
  user-approved deferral, not a pass. Resolution: start/provide the national risk version, run
  the corpus through every exclusion combination, record coverage/matcher timing, and update the
  tested compatibility evidence. Ticket 15 must disclose it.
- The graph archive has not been externally published. The committed manifest template and setup
  command deliberately fail until a real URL/checksum is supplied; this remains a separate
  user-approved deferral that Ticket 15 must disclose.

## 2026-08-01 frontend timing exception

- Environment: Docker Compose using the repository's `node:20-slim` frontend image; the image
  completed its Dockerfile `npm ci` step.
- Command: `docker compose -p road-risk-ticket12-regression -f compose.yaml -f compose.test.yaml run --rm --no-deps frontend npm test`
- Test: `RouteHistoryPanel > renders labels as text, pages, and opens or reruns the selected snapshot`
- Existing threshold: 5.0 seconds, unchanged.
- Observed duration: 5.473 seconds under Docker load.
- Result: timed out. This is not a passing timing result and the full frontend suite is not
  claimed as passing.
- Other observed frontend tests passed: both route-job API tests, all four canonical-network
  API tests, all seven `RouteJobShell` tests, both geocoding API tests, and the
  `RouteHistoryPanel` deletion-confirmation test.
- Exception: the user explicitly approved this single frontend timeout deviation for Ticket 12.

## 2026-08-01 PostGIS emulation startup exception

- Environment: fresh Docker Compose backend regression stack on an ARM64 host using the
  repository's amd64 `postgis/postgis:16-3.4` image under emulation.
- The final foundation stack did not start. Before tests ran, the `initialize` service exited
  with `psycopg.OperationalError: consuming input failed: server closed the connection unexpectedly`.
- PostgreSQL logs identified the known emulation failure mode: a server process exited and the
  database entered recovery.
- Result: this is an infrastructure exception approved by the user. It is not a passing test
  result and not a product test failure. No test, workload, timeout, or threshold was changed.
