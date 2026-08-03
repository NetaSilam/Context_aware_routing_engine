# Grading validation

Run the complete isolated validation package from the repository root:

```bash
./scripts/run_grading_validation.sh
```

The runner creates one fresh unique Compose project per ordered suite. Each project starts a
committed-fixture PostGIS/Redis/Celery stack plus fake OSRM/geocoding, runs exactly one category,
then removes all containers and volumes before the next suite. This prevents a risk-refresh or
history fixture from changing the next suite's expected state. It never downloads the national
graph or calls public Nominatim.

| Claim | Authoritative test/command |
| --- | --- |
| Pure scoring, validation, time, config, and OSRM parsing | `docker compose ... run --rm unit-tests` |
| Real PostGIS fixture, risk refresh, matcher, fake-upstream, jobs, recovery, geocoding, history | `foundation-tests`, `risk-data-tests`, `corridor-matcher-tests`, `osrm-contract-tests`, `route-job-tests`, `route-history-tests`, `geocoding-tests` in the runner |
| Authentication, ownership, hashing, cookie/CSRF, strict request bounds, hidden test routes, internal gateway boundary | `auth-tests`, `abuse-tests`, and `gateway-tests` in the runner |
| Browser journey: signup, profile, geocode, submit/poll/result, URL reload, history reopen/run-again/delete, logout | `e2e-tests` in the runner |
| Concurrent users, rapid submission/polling/login/geocoding, bounded admission | `stress-tests` in the runner |

The stress service uses Locust against the real API, worker, Redis, and PostGIS services. `202`,
`429`, and `503` are explicit expected outcomes at the public boundary. Queue recovery and Redis
degradation are verified by `test_abuse_protection_stack.py`; worker redelivery and duplicate
delivery are verified by `test_route_job_stack.py` and `test_route_job_reliability.py`.

Run an individual category with the same Compose options:

```bash
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm unit-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm foundation-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm risk-data-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm corridor-matcher-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm osrm-contract-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm route-job-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm route-history-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm geocoding-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm auth-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm abuse-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm gateway-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm frontend-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm e2e-tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml --profile stress run --rm stress-tests
```

| Feature area | Executed evidence |
| --- | --- |
| Foundation/migrations/readiness | `test_foundation_stack.py`, `test_health.py`, `test_config.py` |
| Risk refresh and selected matcher | `test_risk_data_stack.py`, `test_corridor_matcher_stack.py`, `test_route_scoring_service.py` |
| OSRM and geocoding upstream contracts | `test_osrm_client.py`, `test_osrm_contract_stack.py`, `test_geocoder_client.py`, `test_geocoding_stack.py` |
| Authentication and session security | `test_auth_stack.py`, `test_application_routes.py`, `test_deployment_gateway_stack.py` |
| Route jobs, recovery, ownership, and result persistence | `test_route_job_stack.py`, `test_route_job_reliability.py`, `test_route_job_validation.py` |
| History/open/run-again/delete | `test_route_history_stack.py`, `RouteHistoryPanel.test.tsx`, browser E2E |
| Abuse limits, capacity, outage behavior, and reconciliation | `test_abuse_protection_stack.py`, Locust workload |
| Frontend route/login/coordinate behavior | `PlanRoutePage.test.tsx`, `CoordinateAcquisition.test.tsx`, `RouteJobShell.test.tsx`, browser E2E |
| Deployment gateway and public boundary | `test_deployment_gateway_stack.py`, `compose.test.yaml` port-reset assertion path |

CI runs the same runner. Developers can run the individual commands listed in the matrix through
the matching Compose service. Backend local tests must use the root Python 3.12 environment:

```bash
.venv/bin/python -m pytest -q -m "not integration" backend/tests
docker compose --env-file .env.test -f compose.yaml -f compose.test.yaml run --rm frontend-tests
```

## Reproducible setup and operation

1. Create the root environment with Python 3.12 and install `backend/requirements.txt` using
   `.venv/bin/pip`. The container images remain the clean-machine authority.
2. Copy `.env.example` to `.env`; replace all placeholders. `FOUNDATION_DATA_MODE=fixture` uses
   only `backend/tests/fixtures/foundation_fixture.sql`. For national data use `verify` and run
   the one-shot initializer/refresh service before API/workers.
3. For deployment graph setup, run the download/checksum command in [osrm/README.md](../osrm/README.md).
   It intentionally fails until the external archive URL and SHA-256 are supplied. The documented
   rebuild command uses the pinned OSRM image/profile.
4. Start the deployment with `docker compose up --build`; only Nginx publishes port 8080. Check
   `/api/health/live` and `/api/health/ready` through that gateway. Scale workers with
   `docker compose up --scale worker=2`.

## Measured evidence and limitations

National refresh evidence is in [RISK_DATA_REFRESH_REPORT.md](RISK_DATA_REFRESH_REPORT.md):
362,922 corridors, 49,941 accidents, 49,646 attributed accidents, 2020–2024, and a 16.557781606822537
accidents/km reference p95. The result is historical accident density, not crash probability;
traffic exposure, direction, reporting, and environmental factors are unavailable. Routing ranks
only OSRM candidates, not globally safest paths.

[CORRIDOR_MATCHER_BENCHMARK.md](CORRIDOR_MATCHER_BENCHMARK.md) records the Apple M5/16 GiB,
PostGIS 16/3.4 environment, selected `sampled-nearest-v1` 100 m / 30 m parameters, 80% coverage
warning threshold, and 30-repeat warm matcher p50/p95. Every short/highway case meets the <1.5 s
through-40 km tier; the 64.98–66.75 km long case meets the <5 s tier. It does not claim typical
or long full-job timing because that measurement has not been recorded.

Two Ticket 13 deployment obligations remain deliberately unverified:

- No published prepared-graph archive URL/SHA-256 exists, so clean-machine graph download cannot
  be verified yet.
- National PostGIS coverage and matcher timing for exclusion-mode routes have not been measured.

The existing 2026-08-01 frontend timing timeout and ARM64 PostGIS-emulation startup crash remain
recorded exceptions in [ROUTING_TEST_EXECUTION_NOTES.md](ROUTING_TEST_EXECUTION_NOTES.md); they are
not presented as passing evidence.
