# Routing Architecture Decisions

## Purpose and status

This document records the decisions for the project's route-planning feature:

```text
coordinates -> OSRM candidate routes -> historical risk per route -> ranked result
```

It preserves the context from the project proposal, the initial TA feedback, the course's
general backend guidelines, and the architecture review. It is the starting point for future
implementation discussions.

These are architecture decisions, not a claim that the current code implements them. The
current routing backend and frontend are a proof of concept. Runtime targets and the exact
PostGIS matching query still need to be verified with benchmarks.

## Requirements that drive the design

The original proposal described:

- A FastAPI web gateway.
- Multiple routes from OpenStreetMap data.
- A data worker that attaches historical accidents and user context to each route.
- A math worker that balances travel time and safety.
- Redis-backed asynchronous work and parallel scoring workers.
- Authentication, rate limiting, internal-only services, and persistent user data.

The proposal's MongoDB choice is not binding. We will use the PostgreSQL/PostGIS database
already used by the foundation data pipeline because spatial queries are central to the
feature and introducing a second database has no benefit.

The TA feedback adds these corrections:

- Accident-data availability must be verified. It is verified: the project has 49,941
  prepared historical accident records and accident-to-corridor attribution data.
- Redis does not automatically recover every dequeued job. The queue must use explicit
  late acknowledgement and redelivery behavior.
- There is one safety/time preference, not two independent weights. `Wtime = 1 - Wsafe`.
- Independent preferences such as avoiding toll roads or motorways should not be confused
  with the safety/time weight.

The general course guidelines require:

- At least two backend images.
- Async and parallel processing for concurrent users.
- Defined behavior for service and worker failures; "the application crashes" is not an
  acceptable response.
- Rate limiting and spam protection.
- Hashed passwords and only one client-facing web container.
- Persistent application data in a database.
- Unit, integration, end-to-end, stress, and security tests that run on a clean computer.
- A `TESTING` environment variable for test-only access where needed.

Because this is an academic project, we need a correct, explainable implementation of the
proposal. We do not need to solve production-grade road-safety prediction or find the globally
safest possible path.

## Decision 1: perform a controlled rebuild, not a full rewrite

We will build a new routing subsystem inside the existing repository. We will not continue
growing the current flat `backend/app/routing_routes.py` proof of concept, but we will also not
discard useful completed work.

Reuse:

- PostgreSQL/PostGIS and the imported foundation data.
- Prepared accidents, canonical corridors, and accident attribution outputs.
- OSRM as the routing engine.
- Authentication behavior after it is covered by tests.
- Existing map/explorer pages and UI pieces when they remain useful.

Replace or substantially refactor:

- The flat routing module and its inline HTTP, SQL, and scoring logic.
- The current per-request raw-accident scan.
- Candidate-relative min-max normalization.
- The route-planning frontend when necessary so its data flow is understood and maintainable.
- Ad-hoc schema creation and large data loading during web-server startup.
- Docker exposure/readiness configuration and the missing backend test suite.

Why: the proof of concept proves that the services can communicate, but it mixes ownership
boundaries, has weak error handling, and contains spatial/scoring behavior that should not
become the final foundation. Reusing the expensive data work avoids an unnecessary rewrite.

## Decision 2: use one public web gateway and internal backend services

Target runtime layout:

```text
Client
  |
  v
FastAPI web gateway (only published port; also serves the compiled React application)
  |
  +-- Redis/Celery broker and result store
  +-- OSRM
  +-- PostgreSQL/PostGIS
  +-- scoring worker pool
```

Redis, OSRM, PostGIS, and workers must not publish client-accessible ports. The scoring worker
may use the same application image as FastAPI with a different command. Together with PostGIS,
Redis, and OSRM, the project comfortably meets the multiple-backend-image requirement.

Why: this directly matches the proposal's FastAPI gateway, makes the security boundary clear,
and lets internal services change without exposing them to clients.

## Decision 3: use asynchronous route jobs with Celery and Redis

The public workflow will be job based:

```text
POST /api/route-jobs            -> 202 Accepted + job_id
GET  /api/route-jobs/{job_id}   -> queued | running | completed | failed
```

FastAPI will validate, authenticate, and rate-limit the request before enqueuing it. A scoring
worker will load the user context, call OSRM, query PostGIS, rank the routes, and store the
result. The frontend will poll for status; SSE may be added later but is not required for this
feature.

Use Celery with Redis rather than hand-written Redis lists or Streams. Required reliability
settings include late acknowledgement, rejection/redelivery when a worker is lost, a bounded
visibility timeout, and bounded retries for transient failures. Route tasks must be idempotent:
running the same job twice must produce the same final result rather than duplicate persistent
side effects.

Why: this implements the proposal's queue and parallel workers, demonstrates the course's async
and parallel-programming requirement, and accurately fixes the TA's concern about Redis job
reassignment. A client can leave while a job is running without breaking the worker.

Transient job state and short-lived results may live in Redis with a TTL. Accounts and user
preferences remain persistent in PostgreSQL. Redis should use a volume and append-only
persistence so a Redis restart is less likely to lose queued work.

## Decision 4: coordinates are the stable input; geocoding is optional

The route API accepts validated origin and destination coordinates. Coordinates can come from
map clicks, browser geolocation, or an address-search feature.

Address geocoding is not part of the core routing calculation and must not be required for
automated tests. If public Nominatim is retained, the gateway must enforce its application-wide
request limit, cache normalized queries, display attribution, and apply spam limits before any
upstream request. Autocomplete must not call the public service continuously.

Why: OSRM consumes coordinates, and making geocoding optional removes an external dependency
from the main feature. It also prevents manual stress tests from accidentally flooding a public
third-party service.

Coordinate validation must reject:

- Latitude outside `[-90, 90]` or longitude outside `[-180, 180]`.
- Non-finite values.
- Identical origin and destination.
- Values outside the supported operating region when a regional boundary is enforced.

## Decision 5: OSRM generates candidates; our system ranks them

The worker calls the self-hosted OSRM service with full GeoJSON geometry and an explicit number
of alternatives, initially `alternatives=3`. Stored hard preferences map to OSRM exclusions:

- `avoid_highways` -> `exclude=motorway`
- `avoid_tolls` -> `exclude=toll`

OSRM must use a pinned image version for both graph preparation and serving. Its prepared graph
must have a documented, repeatable installation path for a clean machine. Compose must include
an OSRM health check rather than assuming the service is immediately ready.

OSRM may return only one route even when alternatives are requested. In that case the result is
valid but must say `risk_choice_available=false`. The UI/report must describe the feature as:

> Risk-aware selection among OSRM candidate routes.

Why: per-request personalized risk cannot be injected into the standard OSRM graph. Reranking
OSRM candidates implements the proposal without building a new routing engine. We accept that
the globally safest possible route may not be one of OSRM's candidates because this is an
academic demonstration.

## Decision 6: precompute corridor risk statistics

The final design will use the canonical corridor layer instead of scanning every raw accident
point for every request. Create an application-owned derived table similar to:

```text
app.corridor_risk_statistics
  corridor_id               primary key
  geometry_2039             corridor geometry in EPSG:2039
  corridor_length_m
  accident_count
  weighted_accident_count   optional severity-weighted value
  first_accident_year
  last_accident_year
  data_version
```

Add a GiST spatial index on `geometry_2039`. Populate this table when the foundation dataset
changes, not during a route request. Foundation tables remain immutable inputs owned by the
data pipeline; this derived table is owned by the routing application.

At runtime, PostGIS will:

1. Transform each OSRM route to EPSG:2039 once.
2. Use the spatial index to find only corridors near the route.
3. Determine how much of each corridor the route uses.
4. Read the already-aggregated accident values.
5. Score all OSRM candidates in one database round trip.

For a corridor `i`:

```text
overlap_fraction(i) = route_overlap_length(i) / corridor_length(i)

route_accident_score =
    sum(accident_count(i) * overlap_fraction(i))

route_risk_density =
    route_accident_score / matched_route_length_km
```

Also calculate:

```text
risk_data_coverage = matched_route_length / OSRM_route_distance
```

Low coverage must be returned as a warning or confidence field instead of silently treating
unmatched road sections as perfectly safe.

Why: this stays close to the proposal's accident-count-per-road-segment design and uses the
existing accident-to-corridor work. Precomputation removes the expensive accident aggregation
from request time. Prorating by overlap avoids assigning all accidents from a long corridor
when a route uses only a small part of it.

### Runtime feasibility

This design is expected to be feasible because the GiST index limits work to corridors near
three route geometries; it does not scan all corridors. Accident counts are already aggregated.
The initial target is below 500 ms for scoring all three candidates on the intended course
machine, but this is a target, not a verified measurement.

We must implement and benchmark the spatial query early. If exact line-overlap calculations are
too slow or unreliable, the approved fallback is to sample a point every 50-100 metres along
the route and map each sample to the closest acceptable corridor. Sampling gives predictable
work while preserving the segment-based scoring idea.

## Decision 7: describe the risk value honestly

The score represents historical accident density near/on matched road corridors. It is not a
prediction of the probability that the current driver will crash.

Traffic exposure, reporting differences, road direction, and every environmental factor are
not available in the current dataset. This limitation is acceptable for the course. Raw
accident counts satisfy the proposal; severity weighting is useful but optional.

Why: naming the value accurately keeps the logic defensible without expanding the project into
a research-grade safety model.

## Decision 8: retain the proposal's weighted cost but change normalization

There is one safety preference:

```text
Wtime = 1 - Wsafe
```

`Wsafe` can use a simple academic rule based on stored driving experience, vehicle type, and
the current day/night context. Avoiding tolls and motorways are separate hard preferences, not
parts of this weight. Day/night must use `ZoneInfo("Asia/Jerusalem")`, not a fixed UTC offset.

### Rejected normalization

Do not min-max normalize time and risk only among the returned candidates. With two routes, the
faster route always becomes time `0` and the slower route becomes time `1`, even if they differ
by only one second. The same loss of magnitude happens to risk.

Example of the problem:

```text
Route A: 60 minutes, risk 100 -> normalized time 0, risk 1
Route B: 61 minutes, risk  10 -> normalized time 1, risk 0
```

The calculation knows only which route is faster/safer, not that the time difference is tiny
and the risk difference is large.

### Chosen normalization

Use a meaningful time penalty relative to the fastest route:

```text
time_penalty =
    (candidate_duration - fastest_duration) / fastest_duration
```

Normalize risk against a fixed, versioned reference derived once from project data, initially a
high-risk percentile such as `reference_risk_p95`:

```text
normalized_risk = min(route_risk_density / reference_risk_p95, 1)
```

Then retain the proposal's final form:

```text
total_cost =
    Wtime * time_penalty + Wsafe * normalized_risk
```

The route with the lowest cost wins. Return raw time, raw risk, normalized values, weights, and
the final cost so the result can be explained and tested by hand.

Why: fixed/reference-based normalization preserves the size of differences and makes the same
route more stable when OSRM happens to return a different set of alternatives.

## Decision 9: use clear routing module boundaries

Target backend structure:

```text
backend/app/routing/
  router.py                  HTTP validation and response mapping
  schemas.py                 public API and OSRM response models
  routing_service.py         job orchestration
  osrm_client.py             OSRM calls and error classification
  route_risk_repository.py   PostGIS route/corridor query
  route_scoring_service.py   pure normalization and ranking code
  time_context.py            Israel day/night calculation
  tasks.py                   Celery route task
```

The scoring service must be pure Python: no HTTP, database, Redis, or global state. This makes
the proposal's math easy to understand and unit test. OSRM responses must be validated rather
than accessed through unchecked dictionaries.

Why: each module has one clear responsibility, and infrastructure can be replaced or faked in
tests without changing the scoring formula.

## Decision 10: apply backpressure and spam protection before expensive work

The gateway must enforce:

- Per-IP request limits.
- Per-user request limits.
- Login-attempt limits.
- Maximum unfinished route jobs per user.
- A global queue-depth limit.
- Polling-frequency limits.
- Request-body and address-query size limits.

When limits are exceeded, return `429` with `Retry-After`. If Redis or another required internal
service is unavailable, return `503`. Invalid input returns `422` and is never queued.

Why: the graders will intentionally send many requests and click repeatedly. Rejecting excess
work early protects OSRM, PostGIS, worker capacity, and external geocoding costs.

## Decision 11: define failure behavior explicitly

| Failure | Required behavior |
|---|---|
| Invalid input | `422`; no job created |
| Missing/invalid authentication | `401` |
| Rate limit or per-user job limit reached | `429` with `Retry-After` |
| Queue unavailable | `503`; web process stays alive |
| Queue overloaded | Reject new work with `429` or `503` |
| OSRM says no route | Job fails with a clear `no_route` reason; no retry |
| OSRM timeout or 5xx | Bounded retry with backoff, then controlled failure |
| Unexpected OSRM response | Controlled upstream/protocol failure, not an unhandled `500` |
| Scoring worker crashes | Late-acknowledged task is redelivered |
| PostGIS temporarily unavailable | Bounded retry, then controlled failure |
| Only one OSRM candidate | Return it with `risk_choice_available=false` |
| Low corridor coverage | Return result with explicit low-confidence warning |
| Client closes the page | Queued/running job continues safely and later expires |

Why: these behaviors answer the course's availability and manual-abuse requirements with
observable results instead of vague claims about redundancy.

## Decision 12: move initialization out of web startup

Use proper database migrations for application-owned schemas and tables. Load or refresh the
large foundation/derived data through a separate one-shot initialization command/service, not
inside the FastAPI lifespan. Track the loaded data version/checksum so a partial or stale load
is detectable.

Why: the public server should not consume large memory and remain unavailable while GeoParquet
files are loaded. Separating initialization also makes failures and clean-machine setup easier
to diagnose.

## Decision 13: testing is part of the architecture

Automated tests must not call public Nominatim or require the full national OSRM graph.

### Unit tests

- Coordinate and request validation.
- Safety-weight calculation and `Wtime = 1 - Wsafe`.
- Time and risk normalization.
- Cost calculation and chosen-route logic.
- Single-candidate and tied-candidate behavior.
- OSRM response parsing and error classification.
- Retryable versus non-retryable failures.

### Integration tests

Use disposable PostGIS, Redis, a real Celery worker, a small deterministic corridor/accident
fixture, and a fake OSRM HTTP service. Verify:

- Hand-calculated route-to-corridor risk results.
- Enqueue -> worker -> completed result.
- Worker failure/redelivery behavior.
- Invalid requests never enter the queue.
- Authentication and stored preferences affect the expected fields.

### End-to-end tests

Start the complete test Compose stack and verify:

```text
signup -> login -> submit coordinates -> queued job
       -> worker result -> chosen route displayed
```

Use a deterministic fake OSRM response for repeatability. Keep a separate optional smoke/manual
test against the real OSRM graph.

### Stress tests

Use a dedicated Locust or k6 container to test concurrent users, rapid polling, one abusive
user, queue overload, and worker scaling. Controlled `429`/`503` responses are acceptable;
process crashes and unbounded queues are not.

### Security tests

- Routing requires login.
- Users cannot read another user's route job.
- Passwords are bcrypt hashes, never plaintext.
- Internal services expose no public ports.
- Test-only endpoints are absent when `TESTING=false`.

Use the course-required `TESTING` environment variable consistently. Tests must boot with a
small committed fixture set and run first try without downloading national data.

Why: the course explicitly grades every test category and manually attempts invalid inputs,
concurrent use, interruption, and spam. Deterministic internal fakes make these tests reliable
on any computer while preserving a separate real-service smoke test.

## Scaling approach

Workers are horizontally scalable:

```bash
docker compose up --scale scoring-worker=4
```

Do not assign fixed `container_name` values to scalable workers. FastAPI performs only cheap
request/status work, Redis buffers short bursts, workers perform route calculations in parallel,
OSRM handles route generation, and PostGIS uses indexed spatial queries. Queue limits provide
backpressure when demand exceeds the machine's capacity.

Why: this is enough to demonstrate a credible scaling path on one academic deployment without
adding Kubernetes or unnecessary infrastructure.

## Implementation and validation order

1. Create migrations and the precomputed corridor-risk table.
2. Prototype the route-to-corridor PostGIS query and benchmark three candidate routes.
3. Choose exact overlap matching or the 50-100 m sampling fallback from measured results.
4. Implement and unit-test the pure scoring formula with a versioned risk reference.
5. Implement and contract-test the OSRM client.
6. Implement the routing service and Celery task.
7. Add job endpoints, ownership checks, rate limits, and queue backpressure.
8. Rebuild the route frontend around job submission and polling.
9. Add integration and end-to-end Compose tests.
10. Add stress/security tests and verify worker scaling.
11. Pin OSRM and document clean-machine graph/data installation.

## Items deliberately left for measurement or implementation

The following are not missing architecture decisions; they require experiments or data:

- The exact corridor-overlap tolerance and minimum accepted overlap.
- Whether exact overlap or 50-100 m point sampling gives the best accuracy/runtime tradeoff.
- The measured scoring latency and final performance target.
- The value of `reference_risk_p95` and the script that calculates it.
- Optional accident-severity weights.
- Result TTL and whether route history becomes a persistent product feature.
- How the national OSRM graph artifact is delivered to the deployment machine.

Record these values here once benchmarks and implementation settle them.
