# Route risk calculation tickets

## 1. Remove the routing prototype and create the async shell

**What to build:** Remove the obsolete synchronous route-planning implementation and establish
the empty boundaries where the new asynchronous feature will be built, while preserving the
existing data explorers and shared authentication UI.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] The synchronous route and geocoding endpoints are removed and no longer registered.
- [ ] The old candidate-relative scoring, raw accident-buffer query, and fixed-offset time logic
      are removed rather than reused.
- [ ] The old routing API client, route response types, form, and result components are removed.
- [ ] The route page is replaced by a compiling asynchronous-job shell with explicit empty,
      submitting, polling, completed, and failed state boundaries.
- [ ] Authentication UI is moved out of routing-specific ownership and still renders from the
      route shell.
- [ ] Existing canonical-network and accident-attribution pages remain present and their
      frontend tests still pass.
- [ ] Ad-hoc application-schema creation and GeoParquet loading are removed from web startup.
- [ ] Obsolete Compose wiring is removed so the next ticket can rebuild it deliberately.
- [ ] Repository documentation states that the temporary post-cleanup state is not the final
      runnable deployment.

## 2. Restore a reproducible application foundation

**What to build:** Restore a bootable development and test environment with explicit schema
migrations, one-shot initialization, validated configuration, PostGIS, and Redis, so later
vertical slices start from a deterministic foundation.

**Blocked by:** 1. Remove the routing prototype and create the async shell.

**Status:** ready-for-agent

- [ ] Application-owned database schema changes are managed by Alembic and never by FastAPI
      startup code.
- [ ] A one-shot initialization service applies migrations and loads or verifies the requested
      foundation-data version before serving processes start.
- [ ] Initialization is idempotent, records source version/checksum information, and fails
      visibly on partial, stale, or missing required data.
- [ ] Development Compose starts PostgreSQL/PostGIS and Redis with health checks and persistent
      volumes; Redis append-only persistence is enabled.
- [ ] FastAPI has validated async database and Redis configuration without usable committed
      secret defaults.
- [ ] Separate liveness and initial readiness endpoints distinguish a running process from
      unavailable required dependencies.
- [ ] A small committed test fixture path can initialize a clean test database without the
      national dataset.
- [ ] Internal services do not publish client-facing ports in the target Compose design.
- [ ] A clean-container foundation test applies migrations, initializes fixtures, and verifies
      PostgreSQL, PostGIS, Redis, liveness, and readiness.
- [ ] Existing explorer APIs are adapted to the new database lifecycle and remain testable.

## 3. Harden authentication end to end

**What to build:** Deliver the complete required account journey through FastAPI and React so
only authenticated users can use application features and route history remains private.

**Blocked by:** 2. Restore a reproducible application foundation.

**Status:** ready-for-agent

- [ ] Users can sign up with normalized email, bounded password, driving experience, vehicle
      type, motorway avoidance, and toll avoidance.
- [ ] Passwords are stored only as bcrypt hashes and never returned or logged.
- [ ] Users can log in, log out, load their profile, and update allowed route preferences.
- [ ] Authentication uses one configurable 24-hour JWT transported in an HttpOnly,
      SameSite-Strict cookie rather than browser local storage.
- [ ] HTTPS deployment enables the Secure cookie attribute, and session responses prevent
      sensitive browser caching.
- [ ] State-changing authenticated requests enforce the chosen origin/CSRF protection.
- [ ] A non-placeholder JWT secret is required; invalid and expired tokens return controlled
      401 responses.
- [ ] Login and signup limits are checked before expensive bcrypt work and fail closed with a
      controlled 503 when shared Redis protection is unavailable.
- [ ] The route page and application features require login before use.
- [ ] Unit, integration, frontend, and security tests cover signup, duplicate email, password
      bounds, stored hashes, correct/incorrect login, cookie flags, expiration, logout,
      preferences, limits, and protected access.
- [ ] Password reset, email verification, refresh tokens, social login, MFA, and session
      revocation are not introduced.

## 4. Build versioned corridor-risk data

**What to build:** Produce an application-owned, validated risk-data version from the prepared
corridors and accident attributions, ready for fast runtime matching and reproducible scoring.

**Blocked by:** 2. Restore a reproducible application foundation.

**Status:** ready-for-agent

- [ ] A derived risk version contains corridor identity, EPSG:2039 geometry, corridor length,
      raw accident count, included year range, source metadata, and a GiST spatial index.
- [ ] Every successfully corridor-attributed accident counts equally, including all confidence
      tiers; unassigned accidents do not count.
- [ ] All years present in the prepared dataset are included and reported.
- [ ] Accident severity does not affect version 1 ranking.
- [ ] The refresh process reports input/output row counts and attribution counts by confidence
      tier.
- [ ] The version computes a finite positive length-weighted 95th percentile using only
      corridors with at least one accident.
- [ ] A new version is built and validated beside the active version, then activated in one
      transaction; failed validation leaves the prior version active.
- [ ] Readiness reports missing, invalid, or incompatible active risk data.
- [ ] Small deterministic PostGIS fixtures verify aggregation, all-year behavior, p95
      calibration, invalid-version rejection, and atomic activation.
- [ ] Refresh timing and storage use are recorded for the real national data without running
      this refresh during a public route request.

## 5. Select and validate the corridor matcher

**What to build:** Compare exact line-overlap and fixed-interval nearest-corridor matching on
synthetic and real routes, select one production matcher, and record the evidence for that
choice.

**Blocked by:** 4. Build versioned corridor-risk data.

**Status:** ready-for-agent

- [ ] An exact buffered line-overlap prototype scores all candidate routes in one indexed
      PostGIS round trip.
- [ ] A 50-100 metre sampling prototype scores the same candidates by deterministic nearest
      acceptable corridor assignment.
- [ ] Each route position contributes to at most one corridor, including around divided roads,
      frontage roads, ramps, and junctions.
- [ ] Unique matched length never exceeds OSRM route length and reported coverage stays within
      0-100%.
- [ ] Hand-written fixtures cover full overlap, partial overlap, gaps, parallel corridors,
      intersections, no matches, and multiple candidates.
- [ ] A fixed representative real-route corpus covers short, long, urban, highway, junction,
      and parallel-road cases with visual route/corridor overlays.
- [ ] Accuracy includes expected synthetic scores, visual correctness, coverage, and score
      stability after small route-geometry shifts.
- [ ] Repeated measurements record warm p50/p95 matching time for three candidates and the
      intended machine specifications.
- [ ] A method must meet the initial p95 target of less than one second for three candidates;
      among passing methods, the more accurate method is selected.
- [ ] The selected tolerance or sample interval and low-coverage warning threshold are recorded
      as validated configuration.
- [ ] Long-corridor examples confirm average-density prorating is acceptable; otherwise the
      result explicitly recommends precomputed smaller risk sections before continuing.
- [ ] The rejected matcher prototype is removed from production code after the decision.

## 6. Implement the versioned scoring contract

**What to build:** Deliver a pure, explainable scoring capability that accepts candidate route
measurements and a snapshotted user context, then deterministically selects the recommended
candidate.

**Blocked by:** 4. Build versioned corridor-risk data.

**Status:** ready-for-agent

- [ ] The safety rule is explicit and versioned: base 0.40, novice +0.20, motorcycle +0.20,
      truck +0.10, night +0.10, capped at 0.90.
- [ ] Cars add no vehicle increment and `Wtime` always equals `1 - Wsafe`.
- [ ] Day is 06:00-18:59 in `Asia/Jerusalem`; all other local times are night.
- [ ] Candidate time penalty is the uncapped difference from the fastest duration divided by
      the fastest duration.
- [ ] Candidate risk is capped after division by the snapshotted nonzero
      `reference_risk_p95`.
- [ ] Total cost applies the complementary time and safety weights exactly once.
- [ ] Equal costs prefer lower duration, then lower risk density, then the original OSRM index,
      using unrounded values.
- [ ] The output includes raw values, normalized values, factor contributions, weights,
      reference value, coverage, warning, final cost, chosen index, and formula/data versions.
- [ ] A single candidate remains valid and reports that no risk-aware choice was available.
- [ ] Risk is named historical accident density/proxy and never crash probability or guaranteed
      safety.
- [ ] Pure unit tests cover context combinations, cap and time-zone boundaries, invalid
      references, normalization, ties, one candidate, low coverage, and explanation fields.
- [ ] When and only when `TESTING=true`, a narrow HTTP scoring endpoint exposes this pure
      contract; it is absent with testing disabled.

## 7. Implement and validate the OSRM contract

**What to build:** Deliver a typed internal OSRM client and deterministic fake upstream so the
route system can request candidates and classify every expected upstream response without
depending on national graph data.

**Blocked by:** 2. Restore a reproducible application foundation.

**Status:** ready-for-agent

- [ ] One OSRM request asks for full GeoJSON and up to three alternatives.
- [ ] The client maps stored motorway/toll preferences to only the supported exclusion
      combinations.
- [ ] Explicit response models validate route presence, finite positive distance/duration,
      LineString geometry, and coordinate shape.
- [ ] One returned candidate is accepted; no candidates and OSRM `NoRoute` become a stable
      non-retryable result.
- [ ] Timeouts and 5xx responses are classified as transient; unsupported options, malformed
      responses, and invalid geometry are controlled non-retryable protocol failures.
- [ ] HTTP connections and response time have validated configurable bounds.
- [ ] A deterministic fake HTTP service implements normal alternatives, one route, no route,
      timeout, delay, 5xx, unsupported option, malformed JSON, and invalid geometry scenarios.
- [ ] Contract/integration tests exercise real HTTP serialization and container networking
      against the fake service.
- [ ] Automated tests never require the national OSRM graph or public network.

## 8. Deliver the first complete route-job slice

**What to build:** Let an authenticated user submit validated coordinates, watch an
asynchronous job, and receive an explainable risk-ranked route on the map through the complete
database, queue, worker, API, and frontend path.

**Blocked by:** 3. Harden authentication end to end; 5. Select and validate the corridor
matcher; 6. Implement the versioned scoring contract; 7. Implement and validate the OSRM
contract.

**Status:** ready-for-agent

- [ ] Route submission accepts strict origin/destination coordinates and optional bounded
      display labels, rejecting malformed, non-finite, identical, or out-of-region input before
      queueing.
- [ ] Submission snapshots authenticated preferences, submission time/context, active risk
      version/reference, formula version, matcher version, and expected graph version.
- [ ] PostgreSQL stores a UUID-owned job and the worker receives only its job ID through Redis.
- [ ] The worker loads the immutable snapshot, requests OSRM candidates, matches all candidates
      in one PostGIS query, ranks them, and atomically saves summary fields, JSONB result, and
      completed status.
- [ ] `POST /api/route-jobs` returns 202 and the job ID; an ownership-filtered status endpoint
      returns queued/running state and the full completed result.
- [ ] Another user's valid job ID returns 404 without revealing ownership.
- [ ] The frontend submits once, polls with bounded backoff, stops on a terminal state, and
      renders the chosen and alternative route lines with every agreed explanatory metric.
- [ ] Low coverage produces a prominent warning but does not remove a candidate from ranking.
- [ ] A single-candidate result is shown honestly without claiming a safety choice.
- [ ] The active job ID is represented in the page URL and a completed result can reload from
      PostgreSQL.
- [ ] Closing/unmounting the page stops browser polling but does not cancel worker execution.
- [ ] Integration and frontend tests cover the complete happy path through real PostGIS, Redis,
      Celery, fake OSRM, public API, and route UI.

## 9. Make route execution recoverable

**What to build:** Make accepted route jobs deterministic and recoverable across duplicate
submissions, publish failures, worker crashes, transient dependencies, page refreshes, and
controlled terminal failures.

**Blocked by:** 8. Deliver the first complete route-job slice.

**Status:** ready-for-agent

- [ ] The client generates one idempotency key per deliberate submission and reuses it only for
      transport retries.
- [ ] PostgreSQL enforces idempotency uniqueness per user and returns the existing eligible job
      rather than duplicating history.
- [ ] Job creation persists before publishing; a publish failure records a controlled enqueue
      failure and returns 503.
- [ ] A same-key retry republishes an eligible failed/stale job without adding a new row.
- [ ] Startup recovery finds sufficiently stale created jobs and safely republishes them.
- [ ] Workers atomically claim a temporary PostgreSQL lease and attempt number; only an expired
      lease can be reclaimed.
- [ ] Celery uses late acknowledgement, redelivery on worker loss, bounded visibility timeout,
      task time limits, process concurrency, and prefetch of one.
- [ ] Conditional terminal writes prevent duplicate or late workers from overwriting results.
- [ ] Only classified transient OSRM/database failures retry with bounded exponential backoff;
      permanent failures are saved immediately.
- [ ] A saved failed job returns HTTP 200 with `status=failed` and a stable failure object.
- [ ] Queue/service access failures use controlled 503 responses and the web process stays
      alive.
- [ ] Refreshing an active job URL resumes polling; logging out or unmounting stops only client
      polling.
- [ ] Integration tests prove duplicate delivery, lease expiry, redelivery, retry exhaustion,
      no-route handling, malformed upstream handling, publish failure, stale-job recovery, and
      client disconnect safety.

## 10. Deliver complete coordinate acquisition

**What to build:** Let a logged-in user reliably choose origin and destination through address
search, map clicks, or numeric coordinates without making public geocoding a dependency of
routing or automated tests.

**Blocked by:** 3. Harden authentication end to end; 8. Deliver the first complete route-job
slice.

**Status:** ready-for-agent

- [ ] Address search is available only after authentication and only after an explicit search
      action, never search-as-you-type autocomplete.
- [ ] Normalized queries are cached and protected by per-user, per-IP, query-length, and one
      application-wide request-per-second upstream limits.
- [ ] The provider URL and identification are configurable, results are restricted to the
      supported Israel region, and required OpenStreetMap attribution is displayed.
- [ ] Redis unavailability or geocoder failure produces controlled feedback without disabling
      map or numeric input.
- [ ] Origin and destination can each be selected on the map with clear markers and edited in
      numeric fields.
- [ ] All three input methods produce the same strict coordinate type consumed by route-job
      submission.
- [ ] Selected address labels are bounded untrusted display text; coordinates remain
      authoritative.
- [ ] Map/numeric selections fall back to formatted coordinate labels and never trigger reverse
      geocoding merely for display.
- [ ] The deterministic fake upstream supplies address matches, empty results, malformed data,
      delays, and service failures.
- [ ] Unit, integration, and frontend tests cover every input path, validation, caching, limits,
      attribution, fallback, and provider failure without public network calls.

## 11. Deliver persistent route history

**What to build:** Let each authenticated user browse, reopen, rerun, and delete their completed
route searches while preserving the exact original calculation and protecting private
locations.

**Blocked by:** 8. Deliver the first complete route-job slice; 9. Make route execution
recoverable.

**Status:** ready-for-agent

- [ ] User-facing history includes completed route searches only; failed jobs remain internal.
- [ ] The list returns compact summary columns without candidate geometry, newest first with
      deterministic offset pagination, a small default, and a hard maximum.
- [ ] The history query has an index covering owner, status, completion time, and deterministic
      tie order.
- [ ] Opening an entry returns and redraws the exact chosen route and every saved alternative
      without calling OSRM.
- [ ] Detail includes address labels/coordinates, risk/time metrics, coverage/warnings, factor
      explanation, and schema/formula/data/matcher/graph versions.
- [ ] “Run again” creates a new idempotent route job from saved coordinates/labels using current
      preferences, time, active data, matcher, and graph without mutating the original.
- [ ] Users can delete one owned completed entry or clear their completed history after UI
      confirmation.
- [ ] Every history lookup and mutation filters by authenticated owner; another user's ID
      returns 404.
- [ ] Saved labels are safely rendered as text and never trusted as HTML.
- [ ] Integration/frontend/security tests cover listing, page limits, deterministic order,
      detail snapshots, old versions, run again, individual/clear deletion, failed exclusion,
      and cross-user access.

## 12. Add complete abuse protection and backpressure

**What to build:** Protect every expensive or sensitive workflow with shared limits and atomic
capacity so concurrent users and intentionally abusive clients receive bounded responses
without filling queues or crashing services.

**Blocked by:** 9. Make route execution recoverable; 10. Deliver complete coordinate
acquisition; 11. Deliver persistent route history.

**Status:** ready-for-agent

- [ ] Redis-backed limits cover IP, authenticated user, login attempts, geocoding, route
      creation, polling, and history mutations before expensive work begins.
- [ ] Request-body, query-length, strict-type, coordinate, pagination, and unsupported-field
      bounds reject invalid work before queueing or upstream calls.
- [ ] Redis atomically reserves both per-user unfinished-job capacity and global capacity before
      a job is created.
- [ ] Every completed, failed, or unrecoverable job releases its reservations exactly once.
- [ ] Startup reconciliation rebuilds or corrects reservation counters from PostgreSQL after a
      Redis restart or leaked reservation.
- [ ] Queue saturation and rate limits return 429 with `Retry-After`; unavailable required
      protection/queue infrastructure returns a stable 503.
- [ ] Route creation, geocoding, signup, and login fail closed while Redis is unavailable;
      bounded safe PostgreSQL reads remain available where designed.
- [ ] Numeric thresholds are validated configuration rather than constants scattered through
      endpoints.
- [ ] Concurrent integration tests prove atomic admission, exact release, reconciliation, and
      no invalid request reaching Celery or Nominatim.
- [ ] Abuse tests prove rapid clicks, repeated retries, aggressive polling, huge invalid input,
      and one abusive user cannot create an unbounded queue or duplicate history.

## 13. Integrate the real OSRM deployment artifact

**What to build:** Make the real self-hosted OSRM service reproducible and compatible with the
selected risk matcher, including every hard preference and a practical graph-delivery path.

**Blocked by:** 5. Select and validate the corridor matcher; 7. Implement and validate the OSRM
contract; 8. Deliver the first complete route-job slice.

**Status:** ready-for-agent

- [ ] The OSRM preparation and serving image is pinned to one tested version.
- [ ] A version-controlled car profile supports normal, motorway exclusion, toll exclusion,
      and combined motorway+toll exclusion in one prepared graph.
- [ ] Graph preparation and serving use the same profile/image/toolchain and include a real
      service health/readiness check.
- [ ] A versioned prepared graph archive is published outside normal Git with a checksum.
- [ ] A documented setup command downloads, verifies, and extracts the archive into an ignored
      data directory.
- [ ] A separate documented command can rebuild the graph from the pinned OSM input and
      profile.
- [ ] The deployment manifest records graph, corridor-risk, and matcher versions as a tested
      combination.
- [ ] Unknown/incompatible combinations fail or degrade readiness rather than silently serving
      unverified matches.
- [ ] Representative real routes meet the recorded coverage and performance gates with every
      exclusion combination.
- [ ] Optional smoke tests verify real graph routing, one/multiple candidate behavior,
      exclusions, and version reporting; authoritative automated tests still use fake OSRM.

## 14. Create the final secure deployment gateway

**What to build:** Deliver the final one-port deployment with compiled React behind Nginx,
internal services, scalable workers, privacy-safe operations, and clear degraded-service
behavior.

**Blocked by:** 9. Make route execution recoverable; 10. Deliver complete coordinate
acquisition; 11. Deliver persistent route history; 12. Add complete abuse protection and
backpressure; 13. Integrate the real OSRM deployment artifact.

**Status:** ready-for-agent

- [ ] The production frontend is compiled in a multi-stage build and served by Nginx rather
      than Vite.
- [ ] Nginx is the only service with a published host port and proxies `/api` to internal
      FastAPI.
- [ ] Nginx applies bounded request-size and relevant timeout behavior without replacing
      FastAPI's user-aware Redis limits.
- [ ] FastAPI, PostgreSQL, Redis, OSRM, workers, and initializer expose no client-facing ports.
- [ ] Worker services have no fixed container name and can be scaled to multiple processes or
      containers.
- [ ] Liveness shows process state; readiness reports PostgreSQL, Redis, OSRM, queue/worker, and
      data-version compatibility degradation.
- [ ] Structured logs and bounded metrics include job ID, stage, duration, attempt, queue
      capacity, upstream failures, and stable error code.
- [ ] Logs never include passwords, tokens, full addresses, or coordinates.
- [ ] Controlled dependency failures keep containers alive where possible and surface 429/503
      behavior instead of unhandled crashes.
- [ ] Deployment security tests prove the one-port boundary, cookie behavior, hidden testing
      endpoints, no secret defaults, and privacy-safe logs/errors.

## 15. Pass the complete grading validation

**What to build:** Provide one reproducible evidence package proving the full feature, every
required test category, measured performance, abuse resistance, and clean-machine setup.

**Blocked by:** 14. Create the final secure deployment gateway.

**Status:** ready-for-agent

- [ ] Separate documented commands exist for unit, integration, end-to-end, security, and
      stress test categories.
- [ ] One authoritative command builds an isolated Compose test stack and runs every required
      category in a defined order using committed fixtures.
- [ ] CI automatically runs all appropriate non-destructive suites.
- [ ] The test stack uses real disposable PostGIS, Redis, and Celery, a hand-written geospatial
      fixture, and deterministic fake OSRM/geocoding.
- [ ] Browser E2E covers signup, login, profile, coordinate acquisition, submit, poll, result,
      refresh recovery, history, run again, deletion, and logout.
- [ ] Security validation covers authentication, ownership, hashing, cookie/CSRF behavior,
      strict validation, hidden testing endpoints, internal ports, and secret handling.
- [ ] Locust covers many users, rapid clicks, repeated login/geocoding/polling, queue saturation,
      client departure, history operations, worker scaling, Redis degradation, and recovery.
- [ ] Stress acceptance requires bounded queue/memory, controlled 429/503 responses, no process
      crash, no cross-user data, and no duplicate history.
- [ ] The real-data benchmark records machine specifications, cold/warm p50/p95 matching and
      full-job times, selected matcher parameters, coverage threshold, worker capacity, pool
      limits, timeouts, retries, and calculated risk reference.
- [ ] A feature-to-test matrix links every claimed feature to actual tests and commands without
      claiming unimplemented coverage.
- [ ] Setup documentation covers environment creation, fixture tests, full-data initialization,
      OSRM graph download/checksum, graph rebuild, worker scaling, expected health, and manual
      operation.
- [ ] The PRD and earlier architecture record are reconciled so the final documentation contains
      no conflicting decisions.
- [ ] The final report states the verified accident/corridor counts, actual accident-year range,
      risk limitations, OSRM-candidate limitation, TA feedback resolutions, and measured rather
      than promised performance.
