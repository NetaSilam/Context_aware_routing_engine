# Project codebase map

This is the current implementation map for the Context-Aware Safe Routing Engine. It is
intended as the first document a team member reads after `README.md`.

## What the application does

The application accepts an origin and destination, creates an authenticated asynchronous route
job, asks OSRM for candidate driving routes, matches those routes to historical accident-risk
corridors in PostGIS, ranks the candidates using the user's preferences and time context, and
stores the result in route history.

The application also exposes two authenticated data explorers: the canonical road network and
the accident-to-corridor attribution output, and a community hazard-reporting forum where
authenticated users can post, comment on, and vote on real road hazards (potholes, flooding,
broken signals, and similar), optionally anonymously. See `docs/FORUM_FEATURE_PRD.md` for the
forum's full design and `docs/forum-feature-tickets.md` for what is implemented versus planned.

The risk value is historical accident density near matched road corridors. It is not a prediction
of an individual driver's crash probability. Forum hazard reports are a separate, unmoderated
social feature and deliberately do not feed into that risk value (see the forum PRD's Problem
Statement for why).

## Runtime flow

```text
Browser
  -> frontend container: Nginx serves the React build and proxies /api
      -> api container: FastAPI validates requests and owns the public API
          -> PostgreSQL/PostGIS: users, jobs, route results, foundation data, risk data
          -> Redis: rate limits, capacity counters, and Celery broker
          -> worker container: executes route jobs
              -> OSRM: returns candidate driving routes
              -> PostGIS: matches route samples to risk corridors
              -> scoring service: calculates explainable costs and chooses a route
```

Startup is deliberately split into stages:

1. `postgres` and `redis` become healthy.
2. `initialize` applies Alembic migrations, loads or verifies foundation data, refreshes the
   active risk-data version, and cold-seeds forum demo data (users, posts, comments, votes).
3. `api` and `worker` start only after initialization succeeds.
4. `frontend` exposes the only host-facing port, normally `http://localhost:8080`.

## Repository layout

| Path | Responsibility | Start here when... |
| --- | --- | --- |
| `README.md` | Quick project overview, startup, and basic test commands | You are new to the repository |
| `PROJECT_REQUIREMENTS.md` | Original consolidated requirements, decisions, and TODO history | You need the course context or original scope |
| `compose.yaml` | Development/deployment service topology | You need to understand containers or startup order |
| `compose.test.yaml` | Test overrides, fake upstreams, and isolated test services | You need to run integration, E2E, or stress tests |
| `data/` | Prepared foundation artifacts loaded into PostGIS | You need to understand source data or risk inputs |
| `backend/` | FastAPI API, database lifecycle, worker code, and tests | You are changing server behavior |
| `frontend/` | React/TypeScript application, Nginx gateway, browser tests | You are changing UI or client API calls |
| `osrm/` | OSRM graph setup, compatibility manifest, and custom profile | You are changing route candidate generation |
| `scripts/` | Repository-level validation entry points | You need the complete grading validation |
| `docs/` | Decisions, measured evidence, test instructions, and planning history | You need design rationale or verification evidence |

## Backend map

### Application entry points and shared infrastructure

- `backend/app/main.py` creates the FastAPI application, registers routers, installs request-size
  limits, and performs stale-job recovery during lifespan startup.
- `backend/app/config.py` loads and validates environment configuration. Required secrets and
  service URLs are intentionally not given usable committed defaults.
- `backend/app/db.py` provides the async SQLAlchemy database engine/session boundary.
- `backend/app/redis_client.py` provides Redis access.
- `backend/app/health.py` implements liveness/readiness endpoints.
- `backend/app/operations.py` contains structured operational logging and related helpers.
- `backend/app/request_bounds.py` rejects oversized bodies/queries and unexpected query fields.

### HTTP/API features

- `backend/app/auth.py` contains password hashing, cookie-based JWT authentication, current-user
  dependencies, and trusted-origin checks.
- `backend/app/auth_routes.py` implements signup, login, logout, profile, and preference updates.
- `backend/app/geocoding/` implements the optional address-to-coordinate API and its upstream
  client. The production configuration points to Nominatim; tests use `backend/tests/fake_geocoder`.
- `backend/app/data_routes.py` serves the canonical-network and accident-attribution explorer
  APIs. These queries are adapted to the artifacts actually present under `data/`.
- `backend/app/routing/route_jobs.py` defines route-job request/response models and endpoints for
  creation, polling, history, reopen, run-again, and deletion.
- `backend/app/forum/routes.py` implements the hazard-reporting forum: post/comment CRUD,
  anonymity-filtered serialization, up/down/none voting with atomically maintained counters, and
  image/video media upload/retrieval for posts and comments (also serves direct-message media,
  see below). Requests are ordinary synchronous FastAPI/PostgreSQL work (no Celery task), since
  posting, commenting, voting, and uploading are bounded writes unlike OSRM/PostGIS route
  scoring. `backend/app/forum/media_storage.py` owns media content-type/size classification and
  the disk read/write helpers backing that volume.
- `backend/app/messaging/routes.py` implements one-to-one direct messages: sending (with an
  optional single image/video attachment via the same `media_storage.py` helpers, in one
  multipart request rather than the forum's create-then-attach pattern), a paged conversation
  view with read-receipt marking, and a conversation-list summary. A DM's media is retrieved
  through the *same* `GET /api/forum/media/{media_id}` endpoint as forum media (ownership-checked
  against `sender_user_id`/`recipient_user_id` instead of post/comment authorship) rather than a
  separate route.
- `backend/app/notifications/service.py` owns notification-row creation (skips self-notifications;
  never fires when a vote is cleared, only when a new up/down vote is set) and Redis Pub/Sub
  publishing, called from the forum vote/comment endpoints and the DM send endpoint after their
  writing transaction has committed. `backend/app/notifications/routes.py` implements the paged
  `GET /api/notifications` list (with `unread_count`), `POST .../{id}/read` and `.../read-all`,
  and the `GET /api/notifications/stream` Server-Sent Events endpoint. Cold seeding is designed
  in `docs/FORUM_FEATURE_PRD.md` but not yet implemented; see `docs/forum-feature-tickets.md` for
  status.

### Route execution

- `backend/app/routing/route_job_tasks.py` defines the Celery worker task, retry/recovery behavior,
  and the worker-side route-job pipeline.
- `backend/app/routing/osrm_client.py` validates the internal OSRM response and maps user
  motorway/toll preferences to supported OSRM exclusions.
- `backend/app/corridor_matcher.py` implements the selected `sampled-nearest-v1` matcher: one
  sample per 100 metres, 30 metre tolerance, deterministic nearest-corridor selection, and an
  80% low-coverage warning threshold.
- `backend/app/routing/route_scoring_service.py` is the pure scoring contract. It combines time,
  historical accident density, user profile factors, and day/night context, then applies stable
  tie-breaking.
- `backend/app/routing/time_context.py` owns the Jerusalem-local day/night calculation.
- `backend/app/abuse_protection.py` and `backend/app/auth_rate_limit.py` enforce admission,
  rate-limit, and capacity rules before expensive work.

### Data initialization and maintenance

- `backend/app/initialize_foundation.py` loads the committed fixture or verifies an existing
  foundation-data version.
- `backend/app/refresh_risk_data.py` builds and validates an immutable corridor-risk version and
  activates it transactionally.
- `backend/app/seed_forum_demo_data.py` cold-seeds the forum with 6 `is_seed_account=true` users,
  9 historical posts (all 7 hazard types), 11 comments, and 24 votes, using deterministic
  `uuid5`-derived IDs and unique-constraint upserts so re-running it converges to the same state
  instead of duplicating rows. Runs last in the `initialize` service's command chain.
- `backend/app/benchmark_corridor_matchers.py`,
  `backend/app/generate_corridor_matcher_overlays.py`, and
  `backend/app/generate_real_route_corpus.py` support matcher measurement and visual evidence;
  they are not public request handlers.
- `backend/alembic/versions/` owns application schema migrations. Do not add application tables
  through FastAPI startup code.

## Frontend map

- `frontend/src/App.tsx` loads the authenticated user and switches between the five pages.
- `frontend/src/pages/PlanRoutePage.tsx` owns route submission, polling, preferences, and history.
- `frontend/src/pages/ForumPage.tsx` owns the hazard-reporting feed: filtering, pagination, post
  creation, and opening a post into `components/forum/PostDetailPanel.tsx` for comments and
  voting.
- `frontend/src/pages/InboxPage.tsx` owns direct messaging: the conversation list, starting a new
  conversation by recipient user ID, and opening a thread into
  `components/messages/ConversationThread.tsx` for sending text/media replies.
- `frontend/src/pages/CanonicalNetworkPage.tsx` and
  `frontend/src/pages/AccidentAttributionPage.tsx` are the two map explorer pages.
- `frontend/src/components/route-jobs/` contains coordinate acquisition, job state rendering, and
  route-history controls.
- `frontend/src/components/forum/` contains the post form, feed list, post detail/comment panel,
  shared vote-button component, and the media gallery that renders uploaded images/videos inline
  (reused by `components/messages/` for message attachments).
- `frontend/src/components/messages/` contains the conversation list/start-conversation form and
  the conversation thread/compose form.
- `frontend/src/components/notifications/NotificationIndicator.tsx` is the session-header
  unread-count badge: opens one `EventSource` per signed-in session, refetches the unread count
  on every open/reconnect, increments on each live event, and marks everything read on click.
- `frontend/src/components/auth/` contains the signup/login/profile UI.
- `frontend/src/components/canonical-network/` and
  `frontend/src/components/accident-attribution/` contain map filters and detail panels.
- `frontend/src/api/` contains typed client calls and response tests for auth, geocoding, explorer
  data, route jobs, the forum, direct messages, and notifications.
- `frontend/src/lib/applyVote.ts` is the pure client-side vote-delta helper shared by the feed and
  post detail views, so an optimistic vote click never needs a full refetch.
- `frontend/src/types/` contains shared TypeScript response/domain types.
- `frontend/nginx.conf` serves the compiled app and proxies `/api` to FastAPI. Only this gateway
  publishes a host port in the normal Compose deployment.

## Data and OSRM map

- `data/README.md` documents the prepared GeoParquet/Parquet inputs and what is intentionally
  excluded, especially traffic-count artifacts.
- `data/prepared_accidents.geoparquet` is the cleaned accident point input.
- `data/prepared_osm_roads.geoparquet` and `data/prepared_official_segments.geoparquet` support
  the road-network foundation.
- `data/canonical_corridors.geoparquet` is the main road-analysis network.
- `data/accident_attributions.geoparquet` links accidents to corridors and supplies the basis for
  risk aggregation.
- `osrm/rebuild_graph.sh` and `osrm/download_graph.py` prepare the local OSRM graph.
- `osrm/road-risk-car.lua` is the OSRM profile used during graph preparation.
- `osrm/deployment-compatibility.json` records the graph/profile compatibility checked by the API.
- `osrm/README.md` documents the graph artifact workflow and the current external-archive deferral.

## Tests and verification

- Backend unit and integration tests are under `backend/tests/`, including
  `test_forum_routes.py`, `test_forum_media.py`, `test_messages_routes.py`, and
  `test_notifications_service.py` (pure vote/serialization/media-validation logic, no database)
  and `test_forum_stack.py`/`test_forum_media_stack.py`/`test_messages_stack.py`/
  `test_notifications_stack.py`/`test_forum_seed_stack.py` (real PostgreSQL/Redis/disk
  integration: CRUD, ownership, anonymity leak checks, vote counters, the dashboard aggregate,
  media upload/retrieval/size/type/ownership/count-cap behavior, DM sending/pagination/
  read-receipts/cross-user isolation, notification creation/anonymity/read-state — including one
  test that opens a real Server-Sent Events connection and asserts a live event arrives — and
  cold-seed idempotency by running the seed CLI twice and diffing the row-count report).
- `backend/tests/fake_osrm/` and `backend/tests/fake_geocoder/` make upstream behavior
  deterministic without public-network or national-graph dependencies.
- `frontend/src/**/*.test.tsx` and `frontend/src/api/*.test.ts` cover component and client
  behavior, including `frontend/src/pages/ForumPage.test.tsx`, `frontend/src/pages/
  InboxPage.test.tsx`, `frontend/src/components/notifications/NotificationIndicator.test.tsx`
  (mocked `EventSource`), `frontend/src/api/messages.test.ts`, and `frontend/src/lib/
  applyVote.test.ts`.
- `frontend/e2e/route-journey.mjs` covers the browser route journey.
- `backend/tests/stress/locustfile.py` covers concurrent and abusive request behavior.
- `scripts/run_grading_validation.sh` is the complete isolated validation entry point, running one
  Compose test service per feature area (see `compose.test.yaml`, e.g. `forum-tests`) in sequence.
  A dedicated `GRADING_VALIDATION.md` evidence report does not currently exist in `docs/` — see
  `docs/DOCUMENTATION_GUIDE.md`'s "Known documentation drift" section before assuming otherwise.

## Where to make common changes

| Change | Main files |
| --- | --- |
| Add or change an API endpoint | Router in `backend/app/`, then matching client/types/tests |
| Change route ranking | `backend/app/routing/route_scoring_service.py` and scoring tests |
| Change route geometry matching | `backend/app/corridor_matcher.py`, benchmark, fixtures, and matcher tests |
| Change job retries/recovery | `backend/app/routing/route_job_tasks.py`, `route_jobs.py`, reliability tests |
| Change user preferences/auth | `backend/app/auth*.py`, migration, frontend auth/profile components, auth tests |
| Change database schema | Add an Alembic migration under `backend/alembic/versions/` and update initialization/tests |
| Change route candidate graph | `osrm/`, Compose OSRM service, compatibility manifest, OSRM tests |
| Change explorer data | `backend/app/data_routes.py`, frontend explorer API/types/pages, fixture/data docs |
| Change the forum (posts/comments/votes/media) | `backend/app/forum/routes.py`, `backend/app/forum/media_storage.py` for uploads, an Alembic migration, `frontend/src/pages/ForumPage.tsx` and `components/forum/`, `docs/FORUM_FEATURE_PRD.md`/`forum-feature-tickets.md` for design intent and remaining scope |
| Change direct messaging | `backend/app/messaging/routes.py` (reuses `backend/app/forum/media_storage.py`), `frontend/src/pages/InboxPage.tsx` and `components/messages/`, `docs/FORUM_FEATURE_PRD.md`/`forum-feature-tickets.md` |
| Change live notifications | `backend/app/notifications/service.py` (create/publish) and `routes.py` (list/read/SSE stream), the `create_notification` call sites in `forum/routes.py` and `messaging/routes.py`, `frontend/src/components/notifications/NotificationIndicator.tsx` |
| Add another long-lived streaming endpoint | Read `request_bounds.py`'s `GET`/`HEAD` exemption comment first — wrapping a `StreamingResponse` in the body-buffer-and-replay middleware pattern hangs the whole server; verify any new streaming endpoint against a concurrent request on a real Compose stack, not just unit tests |

## Important boundaries

- Public clients reach the system through Nginx; API and worker ports are internal Compose
  services.
- FastAPI accepts and persists jobs; workers perform expensive routing and spatial analysis.
- OSRM supplies candidate routes. This project ranks those candidates; it does not compute a
  globally optimal safest route.
- Historical accident density is a proxy metric. Do not describe it as crash probability or a
  safety guarantee.
- The prepared data under `data/` is not raw source data and does not include traffic exposure.
- Forum posts/comments always store the real `author_user_id`; `is_anonymous` controls only
  API-response visibility, never ownership or rate-limit identity. Do not add a code path that
  reveals a true author to another user when `is_anonymous` is true.
- Forum media lives on the `forum_media` Docker volume, not in PostgreSQL. Never serve it from a
  guessable static path — always go through the ownership-checked `GET /api/forum/media/{id}`
  endpoint.
- Direct messages have no separate conversation ID; a conversation is always derived from
  `(caller, other_user_id)`, and every DM query/mutation is scoped that way. Do not add an
  endpoint that accepts a bare message or conversation ID without also filtering by the
  authenticated caller as sender or recipient.
- `RequestSizeLimitMiddleware` skips its receive-buffer-and-replay logic entirely for GET/HEAD
  requests (see `request_bounds.py`). This is not a minor optimization: applying that pattern to
  a long-lived `StreamingResponse` (as the notification SSE endpoint is) hangs the whole server
  for every other concurrent request, not just the streaming one. Any new streaming/long-lived
  endpoint must stay a GET (or otherwise stay excluded from that path), and must be verified
  against a concurrent request on a real Compose stack before being considered done — this class
  of bug does not show up in unit tests or in a single manual request.
