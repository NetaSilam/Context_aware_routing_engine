# Route Risk Calculation PRD

## Problem Statement

The project needs to implement its main route-planning feature as a reliable, explainable
pipeline:

```text
origin and destination -> OSRM candidate routes -> historical risk per route -> ranked result
```

The current backend and frontend routing code are only a synchronous proof of concept. They
mix HTTP calls, SQL, time-context logic, and scoring in one module; scan raw accident points
on every request; normalize only among the current candidates; have weak failure handling;
and do not implement the proposal's Redis-backed workers, persistent route history, spam
protection, or required test coverage.

The replacement must preserve the proposal's intent and address the TA feedback without
turning an academic project into a production routing-research project. It must use the
verified prepared accident and corridor data, correctly explain what its score means, remain
responsive with concurrent users, reject abusive work before it reaches expensive services,
and fail in controlled ways rather than crash.

The course also requires multiple backend containers, persistent data, hashed passwords,
only one client-facing web container, asynchronous and parallel processing, unit,
integration, end-to-end, stress, and security tests, a `TESTING` environment variable, and a
test setup that runs on a clean computer.

## Solution

An authenticated user will search for an origin and destination by address, map click, or
numeric coordinates. The stable routing input is always a validated coordinate pair. FastAPI
will snapshot the request, the user's route preferences, the local time context, and the
active risk-data version into a persistent PostgreSQL job. It will apply Redis-backed spam
and capacity checks, then enqueue only the job ID through Celery.

A worker will claim the job using a PostgreSQL lease, request up to three routes from a
self-hosted OSRM service, match all candidates to precomputed corridor-risk statistics in one
PostGIS query, calculate historical accident density and data coverage, and rank the
candidates using one complementary safety/time preference. The worker will atomically save
the complete result and history snapshot in PostgreSQL.

The frontend will poll with bounded backoff, display the chosen route and all alternatives,
explain every input to the ranking, warn when corridor coverage is low, and preserve the job
ID in the URL so refreshes recover. Completed searches will appear in user-owned history and
can be reopened, deleted, or run again with current context and current data.

The final deployment will expose only an Nginx web gateway. Nginx will serve compiled React
assets and proxy `/api` to internal FastAPI. PostgreSQL/PostGIS, Redis, Celery workers, OSRM,
and FastAPI will not publish client-facing ports. Vite will remain the development server
until the frontend is complete; the Nginx transition happens before final end-to-end,
security, and stress validation.

The product must be described as **risk-aware selection among OSRM candidate routes**. Its
risk value is a historical accident-density proxy, not a prediction that a driver will
crash and not a guarantee of the globally safest possible route.

## User Stories

1. As a new user, I want to sign up with an email and password, so that my profile and route
   history are private.
2. As a new user, I want my password stored only as a secure bcrypt hash, so that a database
   leak does not expose my plaintext password.
3. As a returning user, I want to log in, so that I can use the application and access my
   previous route searches.
4. As an authenticated user, I want my browser session kept in a protected cookie, so that
   application JavaScript cannot read and steal my authentication token.
5. As an authenticated user, I want to log out, so that the browser stops sending my session
   cookie.
6. As a user with an expired session, I want to be asked to log in again, so that expired
   credentials are not silently accepted.
7. As a user, I want to save my driving experience, vehicle type, toll preference, and
   motorway preference, so that route requests use my profile.
8. As a user, I want to search by address, so that I do not need to know geographic
   coordinates.
9. As a user, I want to choose an origin or destination on the map, so that routing remains
   usable when address search is unavailable or ambiguous.
10. As a user, I want to enter or edit numeric coordinates, so that I have an explicit and
    testable fallback.
11. As a user, I want address choices to resolve to visible coordinates before submission,
    so that I know which location will be routed.
12. As a user, I want readable address labels saved with my search, so that history is easier
    to recognize than raw coordinates.
13. As a user, I want routing and scoring to use coordinates rather than address text, so that
    geocoding is not a hard dependency of the calculation.
14. As a user, I want unsupported, identical, non-finite, or out-of-region coordinates
    rejected immediately, so that I do not wait for an impossible job.
15. As an authenticated user, I want to submit a route request and receive a job identifier
    immediately, so that the browser does not hold a long request open.
16. As a user, I want rapid double-clicks and network retries to reuse the same job, so that I
    do not create duplicate route history or waste worker capacity.
17. As a user, I want the active job ID in the URL, so that refreshing the page resumes the
    same job.
18. As a user, I want the page to poll less aggressively when a job takes longer, so that my
    browser does not spam the status endpoint.
19. As a user, I want a route job to continue after I close or leave the page, so that a
    client disconnect does not corrupt background processing.
20. As a user, I want my completed route to appear in history even if I left while it was
    calculating, so that completed work is not lost.
21. As a user, I want the system to request up to three reasonable OSRM alternatives, so that
    historical risk can influence a real choice.
22. As a user, I want a valid single route when OSRM cannot produce alternatives, so that the
    application still works while clearly saying no risk-based choice was available.
23. As a user who avoids motorways, I want OSRM to exclude motorways before ranking, so that a
    chosen route does not violate my hard preference.
24. As a user who avoids toll roads, I want OSRM to exclude toll roads before ranking, so that
    a chosen route does not violate my hard preference.
25. As a user, I want my submitted preferences and time context snapshotted, so that queue
    timing or later profile edits do not change the meaning of my request.
26. As a user, I want day/night determined using Israel's real time zone, so that daylight
    context does not use an incorrect fixed UTC offset.
27. As a user, I want the safety preference derived from a small visible academic rule, so
    that I can understand why the system emphasized safety or time.
28. As a user, I want `Wtime` to equal `1 - Wsafe`, so that there is one understandable
    safety-versus-time preference rather than two conflicting controls.
29. As a car driver, I want the base safety rule applied consistently, so that repeated jobs
    with the same snapshot are deterministic.
30. As a novice driver, I want the rule to add the documented novice increment, so that my
    stored experience affects ranking.
31. As a motorcycle rider, I want the rule to add the documented motorcycle increment, so
    that vehicle vulnerability affects ranking.
32. As a truck driver, I want the rule to add the documented truck increment, so that the
    stored truck option is meaningful.
33. As a night-time user, I want the rule to add the documented night increment, so that local
    trip context affects ranking.
34. As a user, I want each candidate's historical accident density calculated from matched
    corridors, so that the recommendation uses the project's verified accident pipeline.
35. As a user, I want each route position assigned to at most one corridor, so that parallel
    carriageways and nearby roads do not double-count risk.
36. As a user, I want unmatched route distance reported as data coverage, so that missing data
    is not silently presented as certainty.
37. As a user, I want low coverage shown prominently while still receiving a ranked result,
    so that I can interpret the recommendation cautiously.
38. As a user, I want all successfully corridor-attributed accidents counted equally, so that
    version 1 follows the proposal's raw-count formula without invented weights.
39. As a user, I want the result to state the accident-year range and data version, so that I
    know which historical evidence it represents.
40. As a user, I want risk described as historical accident density rather than crash
    probability, so that the application does not overclaim.
41. As a user, I want time differences measured relative to the fastest candidate, so that a
    small delay remains small rather than becoming an arbitrary maximum penalty.
42. As a user, I want risk normalized against a stable project-data reference, so that scores
    do not change merely because OSRM returned a different candidate set.
43. As a user, I want the system to preserve the size of time and risk differences, so that
    the weighted result reflects magnitude as well as ordering.
44. As a user, I want equal-cost routes resolved deterministically in favor of the faster
    route, so that repeated requests do not make arbitrary selections.
45. As a user, I want to compare chosen and alternative route lines on the map, so that I can
    understand the available choices.
46. As a user, I want raw distance, duration, historical risk, normalized values, weights,
    coverage, and total cost for every candidate, so that the selection can be checked by
    hand.
47. As a user, I want a clear explanation of the winning route, so that the recommendation is
    not an unexplained score.
48. As a user, I want completed searches listed newest first in bounded pages, so that history
    remains responsive as it grows.
49. As a user, I want history to show only completed route searches, so that failed attempts
    do not clutter saved routes.
50. As a user, I want to reopen the exact chosen route and all original alternatives, so that
    historical results do not change when data or OSRM changes.
51. As a user, I want to run an old search again explicitly, so that I can compare its saved
    result with a new calculation using current preferences, time, graph, and risk data.
52. As a user, I want to delete an individual history item, so that I control stored location
    data.
53. As a user, I want to clear my route history, so that I can remove all stored route
    locations.
54. As a user, I want another user's route ID to reveal nothing, so that private locations
    cannot be enumerated.
55. As a user, I want controlled failure messages for no-route and service outages, so that a
    failed calculation does not look like an application crash.
56. As a user, I want invalid input rejected before queueing, so that bad requests do not
    consume background resources.
57. As a legitimate user, I want abusive clients rejected before expensive work, so that spam
    does not fill the queue or delay my route.
58. As a legitimate user, I want a clear retry delay after rate limiting, so that I know when
    to try again.
59. As a user, I want persisted history reads to remain available where safe during a Redis
    outage, so that a queue outage does not crash the whole web application.
60. As an operator, I want stale saved-but-not-enqueued jobs recovered after restart or an
    idempotent retry, so that accepted work does not remain stuck forever.
61. As an operator, I want crashed worker tasks redelivered and safely reclaimed after a
    lease expires, so that worker loss does not lose jobs or create simultaneous duplicates.
62. As an operator, I want only transient service errors retried with bounded backoff, so that
    permanent failures do not create retry storms.
63. As an operator, I want atomic per-user and global capacity reservations, so that
    concurrent submissions cannot exceed configured limits.
64. As an operator, I want worker processes to handle different users in parallel, so that
    the service scales without complicated per-candidate task trees.
65. As an operator, I want one indexed PostGIS query to score all candidates, so that database
    connections and round trips remain bounded.
66. As an operator, I want risk-data refreshes to activate only after validation, so that
    users never see a partial risk table.
67. As an operator, I want each job tied to one risk-data version, so that retries and history
    remain reproducible across refreshes.
68. As an operator, I want the OSRM graph, corridor data, and matcher versions recorded as a
    tested combination, so that geometry drift is detected.
69. As an operator, I want separate liveness and readiness information, so that a live but
    degraded process is distinguishable from a crash.
70. As an operator, I want privacy-safe structured logs and bounded metrics, so that failures
    and stress behavior can be diagnosed without logging addresses, coordinates, tokens, or
    passwords.
71. As a grader, I want every required test category available through documented commands,
    so that claimed coverage can be verified.
72. As a grader, I want one authoritative containerized test command, so that the tests run
    first try without host-specific Python, Node, PostGIS, Redis, or national routing data.
73. As a grader, I want test-only internal endpoints absent outside `TESTING=true`, so that
    testing access does not become a production security hole.
74. As a grader, I want deterministic fake OSRM and geocoding behavior, so that external
    network availability cannot change automated results.
75. As a grader, I want the system to return bounded `429` or `503` responses under abuse, so
    that rapid clicks and request floods do not crash processes or create unbounded work.

## Implementation Decisions

1. **Rebuild boundary.** Perform a controlled rebuild of the routing vertical slice, not a
   full application rewrite. Reuse the prepared PostGIS datasets, canonical corridors,
   accident attribution, useful explorer pages, map components, and authentication concepts.
   Do not extend the synchronous routing proof of concept.

2. **Initial cleanup.** The first cleanup removes the old synchronous routing/geocoding
   backend, the old route API/types/form/result frontend, ad-hoc schema creation, web-startup
   GeoParquet loading, and the current Compose wiring. Replace the route page with a minimal
   asynchronous page shell and move authentication UI out of the routing feature. This broad
   cleanup may temporarily make the application unbootable; the next milestone restores it
   on the intended foundation.

3. **Preserved features.** Keep the existing canonical-network and accident-attribution
   explorers and their read APIs unless a shared infrastructure migration requires a small
   adaptation. Authentication is refactored and hardened, not replaced with a hosted identity
   platform.

4. **Runtime services.** The final runtime consists of an Nginx web gateway, an internal
   asynchronous FastAPI API, Redis as Celery broker and rate-limit/capacity store,
   PostgreSQL/PostGIS, one or more Celery scoring workers, and self-hosted OSRM. The worker and
   FastAPI may use the same application image with different commands. No internal service
   publishes a client-facing port. Redis uses a volume and append-only persistence to reduce
   loss of accepted queued messages across a restart.

5. **Frontend serving transition.** Continue using Vite while the frontend is under active
   development. Before final E2E, security, and stress testing, replace the deployed Vite
   runtime with a multi-stage React build served by Nginx. Nginx proxies `/api` to internal
   FastAPI and enforces basic edge limits such as maximum request size.

6. **Database choice.** Use local Docker Compose PostgreSQL/PostGIS, not MongoDB and not
   Supabase for the current implementation. Keep a standard configurable database URL and
   standard PostgreSQL/PostGIS behavior so moving only the database to Supabase later remains
   possible. Supabase Auth is not part of the design.

7. **Schema management.** Use Alembic for application-owned schemas and tables. Do not create
   or evolve them during FastAPI startup. PostGIS-specific SQL may live in Alembic migrations.

8. **Initialization.** Use a dedicated one-shot Compose initialization service. It applies
   migrations, verifies or loads the required foundation-data version, creates or refreshes
   derived risk statistics when requested, validates them, and exits before API/workers start.
   Automated tests use a small committed fixture rather than the national dataset.

9. **Risk-data ownership.** Foundation schemas remain immutable pipeline inputs. The routing
   application owns versioned derived corridor-risk statistics with corridor identity,
   EPSG:2039 geometry, corridor length, raw accident count, accident-year range, source
   metadata, and a GiST geometry index.

10. **Risk-data refresh.** Build a new risk version beside the active version. Validate row
    counts, geometry validity, year range, attribution counts, reference percentile, and
    benchmark compatibility before atomically switching the active version. A failed refresh
    leaves the prior version active.

11. **Included accidents.** Version 1 counts every accident with a successful corridor
    assignment equally, including high-, medium-, and low-confidence assignments. Unassigned
    records do not count. The refresh report records counts by confidence tier so validation
    can reveal systematic problems.

12. **Accident years.** Version 1 uses every year in the prepared dataset. Every result stores
    and displays the first and last included year and the risk-data version.

13. **Severity.** Accident severity does not affect version 1 ranking. Severity-weighted risk
    is an extension point, not current scope. Future support requires a new derived-data and
    formula version, a recalculated risk reference, and new tests; old history stays immutable.

14. **Corridor granularity.** Version 1 uses average accident density across each canonical
    corridor and prorates accident count by the fraction used by a route. The benchmark must
    inspect long-corridor examples. If averaging is clearly misleading, precomputed smaller
    risk sections are the approved replacement; scanning raw accident points per request is
    not.

15. **Candidate matching experiment.** Prototype exact buffered line-overlap matching and
   50-100 metre nearest-corridor sampling. Select one production method from measured
   correctness, coverage, stability, and runtime, then remove the rejected prototype. Among
   methods that satisfy the performance gate, prefer the more accurate method.

16. **Matcher accuracy gate.** Validation combines hand-calculated synthetic PostGIS cases,
    a fixed representative real-route corpus, visual route/corridor overlays, stability under
    small geometry shifts, coverage, and repeated runtime measurements. Include short, long,
    urban, highway, junction, and parallel-road cases.

17. **Unique matching.** Each route position may contribute to at most one best corridor.
    Deterministic nearest/best-match rules prevent parallel roads or carriageways from
    double-counting matched length and accidents. Coverage must not exceed 100%.

18. **Matcher performance gate.** On the documented intended course machine, the initial p95
    target is under one second for matching/scoring all three candidates and under five seconds
    for a complete background job. Measure repeated warm behavior and document machine
    specifications; do not claim an unmeasured target was achieved.

19. **Risk calculation.** For each matched corridor portion:

    ```text
    overlap_fraction = used_corridor_length / full_corridor_length
    route_accident_score = sum(accident_count * overlap_fraction)
    route_risk_density = route_accident_score / unique_matched_route_length_km
    risk_data_coverage = unique_matched_route_length / OSRM_route_distance
    ```

    All candidates are transformed to EPSG:2039 once and scored in one indexed PostGIS round
    trip.

20. **Low coverage.** Always return exact risk-data coverage. A configurable warning threshold
    is chosen from benchmark results. Candidates below it remain rankable, but the UI shows a
    prominent uncertainty warning. Because density divides by matched length, unmatched road
    is not treated directly as zero risk; the warning explains that the result is based on
    incomplete evidence.

21. **Risk meaning.** Call the metric historical accident density or a historical risk proxy.
    Do not call it crash probability, predicted safety, or proof of the safest possible route.
    Traffic exposure, road direction, reporting bias, and unavailable environmental variables
    remain explicit limitations.

22. **Risk reference.** Normalize risk against a fixed, versioned `reference_risk_p95`. Compute
    it as the length-weighted 95th percentile across corridors with at least one accident.
    Zero-risk corridors do not participate in percentile calibration, although a zero-density
    route still normalizes to zero. Reject a refresh if the reference is non-finite or not
    greater than zero.

23. **Time normalization.** Candidate time penalty is relative to the fastest returned
    candidate and is not capped:

    ```text
    time_penalty = (candidate_duration - fastest_duration) / fastest_duration
    ```

    This preserves the magnitude of large delays and introduces no arbitrary acceptable-detour
    constant.

24. **Risk normalization and final cost.** Use:

    ```text
    normalized_risk = min(route_risk_density / reference_risk_p95, 1)
    Wtime = 1 - Wsafe
    total_cost = Wtime * time_penalty + Wsafe * normalized_risk
    ```

    Candidate-relative min-max normalization is rejected because it destroys the magnitude of
    small and large differences and changes when the candidate set changes.

25. **Safety-weight rule.** Use an explicit, versioned academic rule:

    ```text
    base       +0.40
    novice     +0.20
    motorcycle +0.20
    truck      +0.10
    night      +0.10
    maximum     0.90
    ```

    Cars add no vehicle increment. Return each contributing factor. Avoiding tolls and
    motorways are separate hard preferences and never change this weight.

26. **Time context.** Derive day/night at submission from `Asia/Jerusalem`. Day is
    06:00-18:59 local time; all other times are night. Save the local timestamp, context, and
    rule version. Do not use a fixed UTC offset, sunrise service, worker-start time, or
    user-supplied day/night value.

27. **Ranking tie-break.** Rank with unrounded values using this deterministic order:
    `total_cost`, then lower duration, then lower risk density, then original OSRM candidate
    index. Round only for display.

28. **OSRM candidate contract.** Make one self-hosted OSRM request with full GeoJSON and
   `alternatives=3`, meaning up to three alternatives. Never generate fake alternatives or
   claim global safe-path search. A valid single-candidate result sets
   `risk_choice_available=false`. Pin the OSRM image version used for both graph preparation
   and serving, and require a real OSRM readiness check rather than startup ordering alone.

29. **OSRM hard preferences.** Version-control a pinned car profile whose prepared graph
    supports no exclusions, motorway exclusion, toll exclusion, and combined motorway+toll
    exclusion. Map stored preferences to the supported `exclude` values and contract-test all
    combinations.

30. **OSRM artifact.** Publish the full prepared graph as a versioned archive outside normal
    Git. A setup command downloads it, verifies a checksum, and extracts it into an ignored
    data directory. Also document a reproducible graph rebuild. Automated tests never download
    this artifact.

31. **Compatibility manifest.** Record the OSRM graph version, corridor-risk version, and
    matcher version as a tested deployment combination. Exact source-file equality is not
    required, but an unknown combination must not silently pass readiness. Each combination
    must pass representative-route coverage validation.

32. **Coordinate inputs.** The core route API accepts coordinates only. Address search is the
    primary UI, with map click and editable numeric coordinates as fallbacks. This boundary
    makes removing or switching geocoding a small UI/client change rather than a routing
    rewrite.

33. **Coordinate validation.** Reject non-finite values, invalid latitude/longitude ranges,
    identical origin/destination, malformed types, extra unsupported fields, and coordinates
    outside a configurable Israel-area bounding box before job creation. Database constraints
    mirror important invariants.

34. **Geocoding.** Geocoding requires login. Public Nominatim remains optional and isolated
   behind a configurable client. Search happens only after an explicit action, never
   autocomplete. Normalize/cache queries in Redis, enforce per-user/IP limits and a single
   application-wide maximum of one upstream request per second, restrict results to the
   supported Israel region, cap query/body length, send required identification, display
   attribution, and keep map/numeric fallback available during failure. Automated tests use a
   fake provider.

35. **Authentication ownership.** FastAPI owns signup, login, logout, profile lookup, and
    preference updates. Do not adopt Supabase Auth. Reuse bcrypt and JWT libraries; never
    implement password cryptography manually.

36. **Authentication scope.** Support email/password signup, login, logout, current profile,
    preference updates, expiration, protected endpoints, and rate limiting. Password reset,
    email verification, social login, MFA, account recovery, and multi-device session control
    are not required.

37. **Authentication hardening.** Normalize email, validate password minimum and maximum
    lengths, hash only with bcrypt, require a non-default secret through environment
    configuration, rate-limit before expensive bcrypt work, and avoid revealing sensitive
    details. Comprehensive signup/login/profile/security tests are mandatory.

38. **Browser session.** Transport one JWT in an HttpOnly cookie instead of browser local
    storage. Use SameSite Strict, Secure in HTTPS deployment, a suitable path, no-store
    responses for session material, logout cookie clearing, and origin/CSRF protection for
    state-changing requests. Use a configurable 24-hour expiration and no refresh-token or
    server-side revocation system.

39. **Login boundary.** A user must log in before using the application, including geocoding,
    route submission, polling, history, and preference features.

40. **Persistent route jobs.** PostgreSQL is the source of truth from job creation through
    history. A route job stores a UUID, user owner, unique per-user idempotency key, immutable
    request/preference/time/risk snapshots, status, attempts, lease information, timestamps,
    failure code, searchable chosen-route summary fields, version fields, and a complete JSONB
    result snapshot.

41. **History storage shape.** Use explicit columns for ownership, status, origin/destination,
    optional address labels, timestamps, chosen distance/duration/risk, and versions. Store all
    candidate geometry and calculation detail in versioned JSONB. The worker writes summary,
    result, and completed status atomically to prevent disagreement.

42. **Redis responsibility.** Redis is the Celery broker, shared rate-limit/cache store, and
    atomic capacity store. It is not the public job-result store. Celery tasks use
    `ignore_result=True`; PostgreSQL owns results and history.

43. **Task message.** A Celery route task contains only `job_id`. The worker loads the
    immutable input snapshot from PostgreSQL, avoiding duplicate request sources.

44. **Job creation order.** Validate/authenticate/limit first, reserve capacity, save the
    PostgreSQL job, and then publish its ID to Redis. If publication fails, record a controlled
    enqueue failure and return `503`. Retrying the same idempotency key republishes the eligible
    row rather than creating a duplicate.

45. **Save/enqueue recovery.** On web startup, scan sufficiently stale `created` jobs and
    republish eligible ones. A same-key client retry also recovers them. Conditional state
    transitions make duplicate delivery harmless.

46. **Job state.** Public states are queued, running, completed, and failed, with internal
    creation/enqueue failure states as needed. Retrieving a saved failed job returns HTTP 200
    with `status=failed` and a stable error object; access/auth/rate/database retrieval failures
    use HTTP status codes.

47. **Job leases.** Workers atomically claim jobs with a PostgreSQL `lease_expires_at` and
    attempt count. Redelivered work may be reclaimed only after an expired lease. Conditional
    final writes prevent simultaneous or late workers from overwriting a terminal result.

48. **Celery delivery.** Use late acknowledgement, rejection/redelivery on worker loss, a
   bounded visibility timeout, task time limits, low prefetch, and process-based concurrency.
   Start with configurable concurrency and scale worker processes/containers from stress
   measurements. Scalable worker services do not use fixed container names.

49. **Retry policy.** Retry only classified transient OSRM timeouts/5xx and temporary database
    connection failures, using bounded exponential backoff. Do not retry invalid input,
    unsupported OSRM options, no-route results, malformed upstream payloads, or programming
    errors. Exhausted retries become stable persisted failures.

50. **No cancellation in version 1.** Closing the page does not cancel a task. Jobs target
    under five seconds, finish independently, and save to history. Capacity limits prevent a
    user from creating an unbounded number of unfinished jobs.

51. **Idempotent submission.** The client generates one idempotency key per deliberate
    submission and reuses it for transport retries. PostgreSQL enforces uniqueness per user.
    Re-running a historical route intentionally uses a new key and creates a new job.

52. **Public route-job API.** `POST /api/route-jobs` returns `202` and a job ID. One owned
    `GET /api/route-jobs/{job_id}` returns the current state and includes the full result on
    completion. Polling stops at completed or failed, so the large result is transferred once.

53. **Job ownership.** Use random UUIDs and query by both job ID and authenticated user ID.
    Requests for another user's job return `404`, not `403`, to avoid revealing private route
    existence.

54. **Polling.** The frontend polls immediately, then with bounded backoff such as 0.5, 1, and
    2 seconds with a two-second cap. It stops on terminal state, logout, or component unmount.
    Status polling has its own Redis-backed rate limit.

55. **Addressable jobs.** Put the job ID in the route page URL. Refreshing an active job resumes
    polling; opening a completed job reloads the persisted snapshot. URLs never replace server
    ownership checks.

56. **History behavior.** User-facing history lists completed searches only, newest first.
    Failed rows remain internally available for diagnostics and tests. Use offset pagination
    with a small default, hard maximum, deterministic timestamp/ID ordering, and a matching
    composite database index.

57. **History detail.** Reopening history displays the original chosen route and every original
    alternative with raw/normalized metrics, weights, cost, coverage, warnings, address labels,
    and version information. It never calls OSRM merely to display an old entry.

58. **Run again.** An explicit action copies saved coordinates/labels into a new request. The
    new job uses current profile preferences, submission time, active risk data, matcher, and
    OSRM graph. It does not mutate the old snapshot.

59. **History deletion.** Authenticated users can delete individual owned entries or clear
    their completed history. Deletes are ownership-filtered, confirmed in the UI, rate-limited,
    and security-tested. Any future account deletion cascades to owned jobs.

60. **Address labels.** Save optional selected geocoder labels as bounded untrusted display
    text alongside authoritative coordinates. Map/numeric selections fall back to formatted
    coordinates. Never reverse-geocode merely to render history.

61. **Backpressure.** Before expensive work, enforce per-IP, per-user, login, geocoding,
    route-submission, unfinished-job, global-capacity, polling, history mutation, body-size,
    and query-length limits. Exceeded limits return `429` with `Retry-After`; unavailable
    required infrastructure returns `503`.

62. **Atomic capacity.** Redis atomically reserves both a per-user and global unfinished-job
    slot before job creation. Release slots on every terminal outcome. Reconcile counters from
    PostgreSQL after restart so leaked or reset reservations do not permanently block or
    over-admit work. Initial numeric limits are configuration chosen through stress tests.

63. **Redis failure mode.** Fail closed for route creation, geocoding, signup, and login when
    Redis-backed protection or queueing is unavailable. Return a stable `503` plus retry
    guidance. Keep the process alive, and allow safe bounded reads from PostgreSQL where
    practical.

64. **Async boundary.** FastAPI uses asynchronous PostgreSQL and Redis access for concurrent
    gateway work. Celery workers use straightforward synchronous OSRM and PostGIS access in
    isolated processes. Do not force an async event loop into Celery tasks.

65. **Parallelism boundary.** Parallelism is across user jobs through the worker pool. One
    worker scores its up-to-three candidates together in one set-based PostGIS query. Do not
    create per-candidate Celery tasks or three simultaneous database queries.

66. **Error contract.** Invalid requests return 422 without a job. Missing/invalid sessions
    return 401. Limits return 429 with retry information. Queue or required-service outages
    return 503 without crashing FastAPI. OSRM no-route is a non-retryable saved failure. An
    unexpected OSRM body is a controlled protocol failure. Temporary OSRM/PostGIS outages retry
    within bounds and then fail predictably.

67. **Health and observability.** Provide separate liveness and readiness behavior. Readiness
    identifies unavailable PostgreSQL, Redis, OSRM, incompatible data/graph versions, and
    worker/queue degradation. Use structured logs and bounded counters/timings for job stage,
    duration, attempt, queue capacity, upstream failures, and stable error codes. Do not log
    passwords, tokens, full address labels, or coordinates. Prometheus, Grafana, and distributed
    tracing are not required.

68. **Result explanation.** Persist and return original distance/duration, prorated accident
    score, density, unique matched length, coverage, normalized values, reference value,
    weights and factor contributions, final cost, candidate index, chosen index, formula/data/
    matcher/graph versions, year range, warnings, and `risk_choice_available`.

69. **Module ownership.** Keep separate cohesive components for HTTP schemas/routing,
    orchestration, OSRM client and error classification, PostGIS risk repository, pure scoring,
    Israel time context, Celery tasks, job/history persistence, geocoding, authentication,
    rate/capacity limiting, configuration, and initialization. The scoring component has no
    HTTP, database, Redis, or global state.

70. **OSRM response validation.** Parse OSRM through explicit response models, validate route
    presence, finite positive distance/duration, LineString geometry, coordinate shape, and
    supported error codes. Do not use unchecked nested dictionaries.

71. **Strict configuration.** Secrets, URLs, limits, timeouts, versions, bounding box, cookie
    flags, testing mode, and performance-sensitive capacities come from validated environment
    configuration. Development examples contain placeholders only; no usable secret has a
    committed default.

72. **Implementation sequence.** Deliver validated milestones, with tests inside each stage:
    cleanup; new bootable migration/init/Compose foundation; authentication hardening; risk
    data and matcher benchmark; pure scoring and OSRM contracts; persistent jobs/workers/
    history/backpressure; frontend integration; real OSRM profile/artifact; Nginx transition;
    final E2E/security/stress gates and documentation.

## Testing Decisions

1. **Primary testing seam.** The highest and main behavioral seam is the public HTTP route-job
   workflow: authenticate, submit, poll, retrieve, list history, reopen, rerun, and delete.
   This exercises validation, ownership, persistence, queueing, worker execution, and response
   mapping without coupling tests to internal functions.

2. **Internal testing seam.** When `TESTING=true`, application creation registers one narrowly
   scoped test router that can submit already-calculated candidate metrics to the pure scoring
   contract. This supports the course requirement for testing internal worker/model behavior.
   When `TESTING=false`, the routes are not registered and return 404. Do not retain the old
   `ENABLE_TEST_ENDPOINTS` name or expose a general worker-control API.

3. **Pure-unit seam.** Directly unit-test pure scoring, time context, validation, and response
   parsing where HTTP would add no useful confidence. Unit tests must assert externally visible
   inputs/outputs rather than private helper call order.

4. **Good-test definition.** A good test verifies an observable contract, uses deterministic
   data, checks both normal and meaningful edge behavior, and fails for a user-visible defect.
   Avoid tests that merely mirror implementation details, assert mocks were called without
   checking results, or claim coverage for behavior that was not executed.

5. **Unit coverage.** Cover strict coordinates and request schemas; bounding-box and identical
   point rejection; safety factor contributions and cap; `Wtime=1-Wsafe`; Israel day/night
   boundary and daylight-saving behavior; uncapped time penalty; fixed risk normalization and
   cap; invalid/zero reference rejection; total cost; deterministic tie order; single
   candidate behavior; coverage warnings; OSRM model validation and error classification;
   retry classification; idempotency rules; and configuration validation.

6. **Risk integration coverage.** Use a disposable real PostGIS database and small hand-written
   SQL fixtures with known lengths/counts. Cover exact overlap and/or the selected sampled
   matcher, partial use, gaps, one-match-per-route-position, parallel roads, intersections,
   no matches, coverage bounds, multiple candidates in one query, all confidence tiers,
   all-year aggregation, p95 calibration, invalid refresh rejection, and atomic active-version
   switching.

7. **Job integration coverage.** Use real disposable PostgreSQL, Redis, and a real Celery
   worker. Cover enqueue-to-completion, PostgreSQL-only result storage, task messages containing
   only IDs, state transitions, atomic final save, transient retries, non-retryable failure,
   lease expiry and redelivery, duplicate delivery, save/enqueue failure, stale-created
   recovery, idempotent client retry, capacity reservation/release/reconciliation, and invalid
   input never entering the queue.

8. **Fake upstream.** A small deterministic HTTP service in the test Compose stack provides
   fixed OSRM candidates and geocoding results plus configurable timeout, 5xx, no-route,
   unsupported-option, malformed-JSON, invalid-geometry, and delayed responses. This tests real
   HTTP serialization and container networking. Unit tests may still use local mocks for
   isolated client parsing.

9. **Authentication integration/security coverage.** Cover signup, normalized duplicate email,
   password length boundaries, bcrypt hash storage, correct/incorrect login, rate limit before
   hash verification, cookie flags, expiration, logout, missing/invalid session, profile and
   preference updates, CSRF/origin handling, route/geocode/history login requirements, and
   cross-user job/history access returning 404.

10. **History integration coverage.** Cover completed-only listing, newest-first deterministic
    offset pages and hard maximum, compact summaries without route geometry, complete detail
    snapshots with all alternatives, address-label bounds/escaping, old-version display, run
    again creating a new snapshot, individual deletion, clear history, ownership, and failed
    jobs remaining absent from the user-facing list.

11. **Frontend coverage.** Extend the existing React/Vitest/testing-library approach. Test login
    gating, address selection, map/numeric fallback, coordinate state, duplicate-submit
    prevention, idempotency-key reuse for transport retry, bounded polling/backoff, cleanup on
    unmount/logout, URL refresh recovery, queued/running/completed/failed rendering, candidate
    comparison, one-candidate messaging, low-coverage warnings, history paging/detail/delete,
    and run again.

12. **End-to-end coverage.** Start the complete test stack and exercise signup, login, profile,
    geocode or deterministic coordinate input, submit, queued/running polling, worker result,
    chosen and alternative routes, refresh recovery, history reopen, run again, deletion, and
    logout through the browser. The test stack uses fake upstream and the small PostGIS fixture.

13. **Security coverage.** Verify only Nginx has a published port in the final stack; Redis,
    PostgreSQL, OSRM, workers, and FastAPI are not directly reachable from the client network.
    Verify protected endpoints, ownership filtering, cookie settings, password hashing, input
    size/type validation, no secret defaults, privacy-safe error/log output, and absence of test
    endpoints with testing disabled.

14. **Stress coverage.** Use Locust in a dedicated Compose profile to model normal authenticated
    user flows, many simultaneous users, rapid route submissions, aggressive polling, repeated
    login attempts, address-search abuse, one abusive user, queue saturation, users leaving
    mid-job, history listing/deletion, worker scaling, Redis/service degradation, and recovery.
    Successful stress behavior includes bounded queues/memory, controlled 429/503 responses,
    no process crash, no cross-user data, no duplicate history, and recovery after load falls.

15. **Performance coverage.** Separately run the real-data matcher benchmark on the documented
    course machine. Record cold/warm behavior and p50/p95 values for three candidates and full
    jobs. The test must select exact overlap or sampling based on the agreed accuracy and runtime
    gate and record the final tolerance/sample interval and coverage threshold.

16. **Real-service smoke coverage.** Keep optional, clearly labelled smoke/manual tests for the
    pinned real OSRM graph and public Nominatim policy behavior. These are not part of the
    authoritative clean-machine suite and cannot be used to claim deterministic test coverage.

17. **Execution model.** Developers may run targeted Python and frontend tests locally. The
    authoritative documented command builds an isolated Compose test stack and runs unit,
    integration, E2E, security, and stress categories in a defined order using committed
    fixtures. CI runs all appropriate non-destructive suites automatically.

18. **Feature-to-test matrix.** Documentation maps every implemented authentication,
    geocoding, routing, scoring, history, failure, spam, initialization, and deployment feature
    to actual test files and commands. Do not list a test that is absent or a behavior the test
    does not execute.

19. **Existing prior art.** Reuse the repository's React Testing Library/Vitest page and API
    testing style where behavior remains relevant. The current routing code has no acceptable
    backend test seam and is removed rather than preserved as test precedent.

## Out of Scope

- Finding the globally safest path or modifying OSRM's graph cost per user request.
- Building a custom Dijkstra/A* routing engine.
- Claiming that historical accident density predicts individual crash probability.
- Traffic-exposure normalization, road-direction modelling, live traffic, weather, and a
  research-grade safety model.
- Severity-weighted accident ranking in version 1.
- User-selectable accident-year ranges or day/night overrides.
- Per-trip manual safety sliders or preference overrides.
- Exact sunrise/sunset calculation.
- Runtime raw-accident scans as the normal scoring method.
- Automatically cancelling running route jobs.
- Server-Sent Events or WebSockets for route status.
- Permanent Celery result storage in Redis or a Celery database backend.
- Candidate-level relational analytics tables; complete results use versioned JSONB snapshots.
- Showing failed jobs in user-facing route history.
- Automatically recalculating old history entries when opened.
- Automatic history expiration; users control deletion.
- Password reset, email verification, social login, MFA, refresh-token rotation, and global
  session revocation.
- Supabase database or Supabase Auth in the current implementation.
- Self-hosted Nominatim or mandatory geocoding availability.
- Committing the national OSRM graph to normal Git or requiring it for automated tests.
- Running Vite as the final deployed public server.
- Kubernetes, Prometheus, Grafana, distributed tracing, or other production platform work.
- Rewriting the existing data-explorer features solely for architectural consistency.

## Further Notes

- This PRD is authoritative where the earlier routing architecture record conflicts with a
  decision made during the later grill session. The older record must be reconciled before
  implementation begins.
- The source data contains 49,941 prepared accident records and 362,922 canonical corridors.
  Final reports must cite verified values and the actual included year range from the activated
  risk-data version rather than the proposal's older estimate.
- The TA feedback is satisfied by verified accident availability, explicit Celery late-ack and
  redelivery behavior, and one complementary weight pair rather than two independent weights.
- Controlled 429 and 503 responses are correct outcomes under overload. The objective is to
  prevent crashes, unbounded queues, runaway memory, and expensive upstream work; it is not a
  claim that one course deployment can absorb an unlimited distributed denial-of-service
  attack.
- The final numeric request limits, queue capacity, worker concurrency, SQL/HTTP timeouts,
  retry count, worker lease duration, matching tolerance or sample interval, coverage-warning
  threshold, and calculated `reference_risk_p95` are measurement outputs. They must be stored in
  validated configuration and recorded after stress/accuracy benchmarks rather than guessed in
  this PRD.
- The saved result must carry schema, formula, risk-data, matcher, and OSRM graph versions so
  old history remains explainable after later changes.
- Public Nominatim is a replaceable convenience. Its failure must never prevent map/numeric
  coordinate routing, and automated testing must never consume its public quota.
- The final architecture meets the multi-image requirement through the gateway, API/worker
  application image, PostGIS, Redis, OSRM, initializer, and test-only services while exposing
  only the gateway.
- Implementation proceeds through validated milestones: destructive cleanup; bootable
  foundation; authentication; risk benchmark; scoring/OSRM contracts; jobs/history/protection;
  frontend; real OSRM artifact; final Nginx and full-system validation. Each milestone adds its
  relevant tests before the next begins.
