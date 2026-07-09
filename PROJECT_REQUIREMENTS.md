# Context-Aware Safe Routing Engine — Requirements & Guidelines

**Course:** Software Engineering for ML (Spring 2026)
**Team:** Neta Silam (211569637), Rotem Borenstein (211620570), Yam Ben Tov (314745860)
**Foundation repo (data/mapping pipeline, reused as an input — not the project repo):** [github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine](https://github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine)
**Project repo:** [github.com/NetaSilam/Context_aware_routing_engine](https://github.com/NetaSilam/Context_aware_routing_engine) (scaffolded — compose.yaml, seed-loading Postgres/PostGIS, minimal FastAPI backend)
**Presentation:** 2026-07-16 (10 days out) — needs a demo-able MVP
**Final submission:** 2026-08-23

This document consolidates `Proj_Guidelines.pdf`, our `Project_Proposal.pdf`, and the TA
feedback in `feedback.md` into one working spec, resolves the open feedback items, and
locks in decisions for the two undecided features (forum, LLM). Treat it as the living
source of truth — update it as decisions change instead of re-deriving from the PDFs.

---

## 0. Foundation pipeline — what we're carrying over into the new repo

**Correction from earlier in this doc:** the repo below is *not* the project repo. It's a
separate, already-built data/mapping pipeline (accidents → road corridors, on a map) that
we are reusing as an input. The actual course project — routing engine, auth, long-term
memory, forum, LLM, deployment — gets built in a **new repository**, with this pipeline's
output (and, selectively, its serving code) carried over rather than rebuilt from scratch.
Everything below was verified directly against
[github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine](https://github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine)
(master, commit `fec645d`), not just the two overview docs.

**Stack actually in place (differs from the original proposal — update accordingly):**
Python data pipeline + **FastAPI** backend + **PostgreSQL/PostGIS** (not MongoDB) +
**React/TypeScript (Vite)** frontend. `compose.yaml` currently runs only the `postgis`
service — the web container, Redis, and worker containers all still need to be added.

**What's built and working:**
1. **`foundation_data`** — cleans the raw accident export, official road-segment
   reference data, and a Geofabrik Israel OSM road extract; matches official segments to
   OSM roads.
2. **`canonical_network`** — turns raw OSM lines into a proper routable structure:
   splits roads into connection-aware **atoms**, groups atoms into **logical roads** and
   then **corridors**, and builds node-level connectivity (`graph.py`) between atoms.
   This connectivity graph is the closest thing this codebase has to a routing graph today.
3. **`accident_attribution`** — assigns each historical accident to the nearest suitable
   corridor within a 100m radius, with a confidence tier (high/medium/low), ambiguity
   detection (near-ties), and official road-number cross-checks. This **directly answers
   the TA's "did you verify availability of accidents data?" feedback** — not only is the
   data available, it's already cleaned, geocoded, and attributed to road corridors with
   an explicit confidence/quality signal per accident.
4. **`traffic_coverage`** — a fourth pipeline stage that exists in the repo (`scripts/traffic_coverage/`,
   `run_todo3_traffic_coverage.py`) but isn't covered by either overview doc. Get a
   one-paragraph explanation from whoever built it before relying on it in the write-up —
   don't guess at what it does from the file names alone.
5. **Backend API** — read-only query endpoints over the precomputed PostGIS data:
   `/api/canonical-network/...`, `/api/accident-attribution/...`, `/api/traffic-coverage/...`
   (summaries, bbox-filtered lists, per-item detail). No auth/JWT yet.
6. **Frontend** — a page-switcher app with three explorer pages (canonical network,
   accident attribution, traffic coverage) for visualizing the pipeline outputs on a map.
   No "enter origin + destination, get a route" UI yet.
7. **Tests** — real unit tests per pipeline stage, plus backend API/repository/service
   tests and an ETL-runner integration test. This is a solid head start on the mandatory
   test suite (§5's testing constraint).

**What's genuinely still missing** (this is the actual gap to close, not "start over"):
- Turning "risk per corridor" into "given point A and B, rank alternative routes" — i.e.
  the proposal's Worker A/B split and the `Cost(R) = Wtime·Time + Wsafe·Risk` function
  don't exist yet. The corridor risk-density data is the *input* this still needs; see §1.3.
- No routing API/engine producing actual route alternatives + travel time yet (§1.3).
- No user accounts, auth, JWT, or long-term preference storage.
- No Redis/task queue or worker containers in `compose.yaml`.
- No forum, DMs, notifications, or LLM integration (expected — new work for this course).
- No root-level `README.md` yet (only `backend/README.md` and `frontend/README.md`
  bootstrap notes exist) — the course requires one at the repo root with run + test
  instructions; `TODO.md`/`docs/` exist locally but are gitignored, so nothing in them is
  visible on GitHub today.

### 0.1 How this becomes the new repo — done for the data, pending for the serving code

**Status: implemented.** `data/` now holds the foundation pipeline's actual parquet/geoparquet
exports (added directly to this repo, with its own `data/README.md`), not a `pg_dump` as
originally planned here — simpler, since it doesn't require a live Postgres instance to
export from, just the artifact files. `backend/app/seed.py` loads them into PostGIS on
first `web` container startup (checks row counts, skips if already seeded), writing into
the **same schema/table names the foundation repo's backend queries use** —
`canonical_network.canonical_corridors`, `canonical_network.official_segment_links`,
`accident_attribution.accident_attributions`, `accident_attribution.accident_attribution_summary`,
plus the upstream `foundation_data.*` tables — verified directly against
`backend/app/repositories/{canonical_network,accident_attribution}.py` in the foundation
repo so those files can be ported without renaming anything.

**Known gap, found while checking this (don't assume a clean port):** the foundation
repo's `list_corridors_in_bbox` query joins `canonical_corridors` against a
`canonical_corridor_display` table (a simplified display geometry, per the foundation
project's own docs), and `get_corridor_detail` left-joins `canonical_roads` — **neither
table is in this `data/` export** (it's deliberately a reduced "non-traffic downstream
artifacts" subset, per `data/README.md`). Two ways to close this when porting the serving
layer (§0.1 step 2 below): (a) get the missing tables exported too, or (b) adapt those two
queries to use `canonical_corridors.geometry` directly and drop the `canonical_roads` join
— acceptable for this project's purposes, just means the map returns full-resolution
geometry instead of a simplified display version, and corridor detail won't show road-level
fields. The `canonical_network` `/summary` endpoint depends entirely on audit tables that
also aren't in this export and won't work either way unless those are added.

**Status: done for corridors + accidents.** `backend/app/data_routes.py` serves
`canonical_network.canonical_corridors`(+detail), `accident_attribution.accident_attributions`
(list+detail+filters), and the accident summary — hand-adapted (not a straight copy) to
close the gap above, since the original repo's `repositories/`/`schemas/` layer expects
fields (`canonical_corridor_display`, `canonical_roads`, audit tables) that aren't in this
data export. Not ported: `canonical_network`'s `/summary` (needs the missing audit tables)
and all of `traffic_coverage` (no data for it in this export).

**Frontend: also done.** The React/Leaflet frontend (`frontend/`) was ported from the
foundation repo - two pages (Canonical Network, Accident Attribution), dropping the
Traffic Coverage page entirely (no data). Its typed API client (`src/api/*.ts`) has
strict runtime parsers that expect an exact response shape, so `data_routes.py` was
written to match those shapes field-for-field rather than inventing a simpler one -
verified by running the frontend's actual test suite (4 suites, 9 tests, all passing),
`tsc` typecheck + production build, and an end-to-end check through the real Docker
network (frontend's Vite dev-server proxy → backend → seeded PostGIS, real Tel-Aviv-area
data rendered, Hebrew corridor names intact). The backend container has no `ports:`
mapping anymore - only `frontend` (http://localhost:5173) is exposed to the host, matching
the "only the web container is exposed to clients" constraint from the guidelines.

---

## 1. Recommendation on the two open features

### 1.1 Forum → dangerous road / hazard reporting (recommended)

Don't build a generic Reddit clone bolted onto the side of the router. Frame the forum as
a **crowd-sourced hazard-reporting feed**: potholes, flooding, broken traffic lights, poor
lighting, illegal speed bumps, a crash that just happened, etc. This is a better fit than
it looks, because every mandatory forum sub-requirement maps onto it directly, *and* it
strengthens the core pitch instead of being a bolted-on distraction:

| Mandatory forum feature | Hazard-reporting mapping |
|---|---|
| Public posting (title, body, image, video) | "Report a hazard": type, description, photo/video of the road issue |
| Anonymity toggle | Realistic — people reporting speed cameras/police often want anonymity |
| Comments | "Still there today" / "cleared now" confirmations from other drivers |
| Upvote/Downvote + profile dashboard | Confirm/refute a hazard (Waze-style trust signal); dashboard tracks a user's reporting reputation |
| DMs | Ask a reporter for more detail / coordinate carpool around a closure |
| Live notifications | Notify users subscribed to an area/route when a new hazard appears or their report gets confirmed |
| Rate limiting / spam defense | Critical here — fake hazard spam is actively harmful, not just annoying |
| Cold seeding | Pre-seed fake accounts + historical hazard reports so the feed looks alive |

**Payoff beyond the checklist:** confirmed hazard reports become a second, *live* input
into the same risk-scoring pipeline (Worker A/B) that today only reads the static ~50k
accident dataset. That gives a direct answer to the TA's feedback question about accident
data availability — the static dataset is the historical baseline, the forum is the live
supplement — and it's a genuine product idea, not decoration.

### 1.2 LLM → analyzing/studying reports (recommended)

Two concrete LLM-backed jobs, in priority order:

1. **Hazard report triage & dedup (primary).** Free-text (+ optionally image) reports get
   classified into `{hazard_type, severity, road_segment}` and near-duplicate reports
   about the same spot get merged into one canonical hazard entry instead of flooding the
   feed with 10 posts about the same pothole. This is the better fit for the mandatory
   job-queue requirement: report length/complexity varies a lot, which is exactly what
   you need to demonstrate a real "estimate how long this job will take" heuristic
   instead of a fake one.
2. **Route explanation (secondary, do only if time allows).** Turn the numeric cost
   breakdown (`Wsafe`, `Wtime`, risk density) into a one-paragraph plain-language "why
   you got this route" explanation, personalized using the user's long-term profile.
   Nice demo feature, not load-bearing for grading.

Use an API-based LLM (Gemini/OpenAI/HF — all three are already anticipated in the
guidelines' example `.env`) rather than hosting weights yourselves; "local" in the
guidelines' feature name means "integrated into your stack," not "self-hosted weights."
Confirm this reading with the TA if in doubt (see §6).

### 1.3 Finding a free routing API (the actual missing piece)

The existing repo already produces a road network (`canonical_network`) and a
risk-density-per-corridor layer (`accident_attribution`) — what it doesn't have yet is a
source of **candidate routes with travel time** between two arbitrary points. Options,
ranked:

1. **Self-hosted OSRM in Docker (recommended).** OSRM is free, open-source, and has zero
   rate limits because you run it yourself. You already download a Geofabrik Israel
   extract for `canonical_network` — feed the same `.osm.pbf` into `osrm-extract` +
   `osrm-contract`, then run `osrm-routed` as its own Compose service. Query it for
   `alternatives=true` to get several candidate routes with geometry + ETA. This matches
   the proposal's original design ("fetches baseline paths from an OSM server") and fits
   the course's "extra Docker image" pattern directly — it's a new container, not a new
   external dependency to worry about at grading time. Glue step: snap each OSRM route's
   coordinates onto your corridor layer using the *same* nearest-corridor matching logic
   `accident_attribution` already implements (§0.3) — you're reusing, not rebuilding,
   the spatial-join logic to compute `S(R) = ΣC(i)/ΣL(i)` for each candidate route.
2. **OpenRouteService (ORS) free API key.** Zero self-hosting, 2,000 requests/day free
   tier, and it natively supports `avoid_features=["tollways","highways"]` — which maps
   directly onto the Long-Term Memory preferences in §4.2 for free. Simpler to stand up,
   but adds an external network dependency and a daily quota to watch during grading/demo
   traffic (manual testers hammering the app, per the guidelines' "manual tests" section).
3. **Your own graph as the router (stretch, not near-term).** `canonical_network/graph.py`
   already builds node-level connectivity between atoms — in principle you could run
   Dijkstra/A* directly over it instead of calling an external router at all, which would
   be a genuinely distinctive "we built the whole thing ourselves" story. Don't start here
   under a 10-day-to-presentation clock: it needs real edge weights (speed by road class,
   turn restrictions) that don't exist yet. Worth revisiting after the Jul 16 MVP if time
   allows, as a complexity/creativity add-on.

Recommendation: build option 1 for the MVP; keep option 3 in your back pocket as the
"complexity and creativity" talking point in the final report even if you don't ship it.

**Status: option 1 implemented and verified.** OSRM runs as its own `compose.yaml` service
(`osrm/osrm-backend`, `osrm-routed --algorithm mld`), against the Israel/Palestine extract
prepared once via `osrm-extract`/`osrm-partition`/`osrm-customize` (see `osrm/README.md` —
took under 2 minutes total, not committed to git, ~650MB regenerated on demand). Verified
`exclude=motorway` genuinely changes the returned route (confirmed via direct query before
wiring it into the backend); `POST /api/route` calls it with `alternatives=true` and the
user's stored `exclude=` preferences.

**Geocoding — real constraint discovered, plan adjusted.** OSRM only accepts coordinates,
so an address needs a geocoding step first. Self-hosted Nominatim was the original plan
(built from the same Israel `.osm.pbf`), but importing it requires several GB of free RAM
during indexing — on the dev machine used for this project (8GB total), running Nominatim's
import alongside Postgres + OSRM + the app containers exhausted memory badly enough to
crash the Docker daemon itself, twice. **Current implementation instead calls the public
Nominatim API** (`https://nominatim.openstreetmap.org`) with a proper `User-Agent` header
per its usage policy, since a course demo's request volume (occasional single-address
lookups on button click, not autocomplete) is a different traffic profile than the
autocomplete/bulk-use case that policy's rate limits actually target. This is a real
trade-off, not a free lunch — document it as such in the report:
- **Pro:** zero local resource cost, works today, verified against real Hebrew addresses
  (e.g. "דיזנגוף 100 תל אביב" → correct coordinates).
- **Con:** external dependency at demo time (no internet = no geocoding), and the
  guidelines' promised manual stress test ("send 999999999 requests to some endpoint")
  must not be pointed at `/api/geocode` specifically, or it'll get you rate-limited/blocked
  by an external party, not just your own server.
- **If self-hosting Nominatim later** (e.g. on the course's Azure VM, which likely has more
  RAM than this dev machine): swap `NOMINATIM_BASE_URL` to point at it — the code doesn't
  otherwise change (`backend/app/routing_routes.py::_nominatim_base_url`).

Flow as implemented: address text → `GET /api/geocode?q=...` → Nominatim → candidate
coordinates (frontend shows a picker if more than one match) → user confirms → `POST
/api/route` with those coordinates → OSRM → Worker A/B.

### 1.4 Influencing OSRM's route with risk data + user preferences

OSRM does **not** accept a custom cost/weight per request — its routing cost function is
baked into the graph offline (`osrm-extract`/`osrm-contract`, driven by a static Lua
profile), not something you can inject at query time. So Worker A/B has to sit as a
**layer on top of OSRM**, not a patch inside it. Three mechanisms, each for a different job:

1. **Hard user preferences (avoid tolls/highways) → OSRM's native `exclude=` param.**
   The standard `car.lua` profile already defines excludable classes (`motorway`, `toll`,
   etc.), chosen per request:
   `GET /route/v1/driving/{coords}?exclude=motorway,toll&alternatives=true`.
   This maps directly onto the Long-Term Memory preferences in §4.2 — free, built-in, no
   graph rebuild needed.
2. **Risk-based ranking → re-rank OSRM's `alternatives`, don't fight OSRM for it.**
   Request `alternatives=true` (returns ~2-4 candidates, and only if OSRM judges them
   "reasonably different" from the fastest — for some origin/destination pairs there may
   be only one route on offer; call that limitation out explicitly in the report rather
   than overselling it). For each candidate, snap its geometry onto the corridor layer
   (reusing `accident_attribution`'s nearest-corridor matching) to get `S(R) = ΣC(i)/ΣL(i)`,
   combine with OSRM's `duration` for `NormalizedTime(R)`, and pick the route minimizing
   `Cost(R) = Wtime·NormalizedTime(R) + Wsafe·NormalizedRisk(R)`. This is genuinely a
   *selection* among OSRM's own candidates, not a modification of OSRM's search.
3. **(Stretch, not Phase 1) Risk-weighted OSRM profiles.** For OSRM itself to physically
   route around dangerous roads rather than just picking among what it already offered,
   you'd inject a `risk_score` tag per way into the `.osm.pbf` (derived from
   `accident_attribution`) and write a custom Lua profile that inflates `weight` (not
   `speed`) accordingly — then rebuild the graph. Because `Wsafe` is personalized
   per-request (driving experience, vehicle type, day/night), you can't bake a continuous
   per-user weight into a single static graph; the practical version is 2-3 discretized
   profiles (e.g. normal / cautious / very-cautious), chosen by bucketing the user's
   computed `Wsafe`, each requiring its own prebuilt OSRM graph. Worth a mention in the
   report's "complexity and creativity" section even if only options 1-2 ship.

---

## 2. Resolving the TA's feedback on the proposal

| Feedback | Resolution |
|---|---|
| "What will be the UI, desktop or mobile?" | Web app, desktop-first. Backend is graded, not visual design, so keep the frontend minimal (a map view + forms) and don't invest in mobile. |
| "Did you verify availability of accidents data?" | **Open TODO, blocking.** Must be resolved before Worker A development starts — see §7.1. |
| "Did you calculate by hand a few items to compare against Waze?" | Optional but cheap validation — add as a manual sanity-check task during testing phase (§7.4), not a blocker. |
| "Redis reassigns it [the job]" — doubted | Correct catch: a plain Redis list (`LPUSH`/`BRPOP`) does **not** auto-redeliver a job an already-dequeued worker crashed on. Fix the architecture (see §3) instead of restating the incorrect claim in the report. |
| "Minor: there's a single weight (the other is complementary)" | Correct — `Wtime = 1 − Wsafe` is one degree of freedom. Long-Term Memory (§4.2) should introduce genuinely independent preferences (e.g., avoid tolls, avoid highways) rather than just tuning the one safety/time knob. |

---

## 3. Architecture fix: job reliability (replaces the incorrect Redis claim)

Pick one, document it explicitly in the report's Risk Assessment section:

- **Option A — Redis Streams + consumer groups.** Workers `XREADGROUP` jobs; on crash,
  unacked entries are reclaimed via `XAUTOCLAIM` after a visibility timeout and
  redelivered to a live worker. This is the accurate version of what the proposal
  originally claimed.
- **Option B — Celery with Redis broker**, `acks_late=True` + `task_reject_on_worker_lost=True`.
  Gives you retries, visibility timeouts, and the parallel worker pool for free, at the
  cost of an extra dependency.

Recommendation: **Option A** if you want to keep the stack lean (you already committed to
raw Redis in the proposal); **Option B** if you'd rather not hand-roll retry/visibility
logic. Either way, this same primitive is what backs the LLM job queue in §4.3 — build it
once, reuse it for both the routing workers and the LLM workers.

Updated component list (revised to match the stack actually in the repo — Postgres/PostGIS,
not MongoDB — rather than the proposal's original wording):

1. **Web Gateway (FastAPI)** — already exists; needs auth, rate limiting, and new
   forum/DM/LLM-job endpoints added alongside the existing canonical-network/accident-attribution/traffic-coverage routes.
2. **Routing engine (OSRM container)** — new; see §1.3. Feeds candidate routes + ETA to the scoring step.
3. **Task Queue (Redis Streams or Celery/Redis)** — new; routing-scoring jobs + LLM jobs, each in their own stream/queue.
4. **Scoring Workers (Python)** — new; reuses the existing corridor/accident-density data (`accident_attribution`) plus the OSRM output to compute `Cost(R)`.
5. **LLM Workers (Python)** — new; hazard triage/dedup, optional route explanation.
6. **Database (PostgreSQL/PostGIS)** — already exists for the accident/road pipeline data; extend it with new tables for user profiles/preferences, forum posts/comments/votes, DMs, and notifications rather than introducing a second database technology.
7. **Notification channel (WebSocket or SSE from the Web Gateway)** — new; for live forum/DM/vote notifications.

The mandatory "at least two backend images" is already satisfied today (web + postgis).
Adding OSRM, Redis, and the worker pool comfortably clears the minimum and gives a real
answer to the "scalability" risk-assessment question (additional worker containers can be
started to drain the queue under load).

---

## 4. Functional requirements by graded component

### 4.1 Core Routing Engine — 60 pts (from the proposal)

**Status: core loop implemented and verified end-to-end** (`backend/app/routing_routes.py`),
against real seeded data, through the actual frontend → backend → OSRM/Postgres network
path (not just unit-level): a real Hebrew address pair ("דיזנגוף 100 תל אביב" → "כיכר רבין
תל אביב") resolves through geocoding, OSRM returns candidate routes, and the response comes
back with a real accident count and risk density pulled from the seeded
`accident_attribution` data.

- `GET /api/geocode?q=...`: address text → candidate coordinates (§1.3; public Nominatim,
  not self-hosted — see the constraint documented there).
- `POST /api/route`: accepts origin/destination coordinates + optional `time_of_day`,
  requires a valid JWT, calls OSRM with `exclude=` set from the user's stored preferences
  and `alternatives=true`.
- Worker A (`_accident_count_near_route`): rather than snapping onto the corridor layer as
  originally planned, this buffers each OSRM candidate's route geometry by 30m (in the
  ITM/EPSG:2039 analytical CRS) and counts real accident points from
  `accident_attribution.accident_attributions` that fall inside it — simpler than
  corridor-matching and avoids depending on corridor topology accuracy; risk density =
  accident count ÷ route length in km, using OSRM's own `distance` field.
- Worker B (`_safety_weight` + cost loop in `plan_route`): `Wsafe` starts at 0.4 and adds
  0.2 for a novice driver, 0.2 for a motorcycle, 0.1 for night — clamped to [0.1, 0.9],
  directly implementing the proposal's "novice motorcyclist at night → high Wsafe" example.
  `Wtime = 1 - Wsafe`. Candidates are min-max normalized on time and risk, and
  `Cost(R) = Wtime·NormalizedTime(R) + Wsafe·NormalizedRisk(R)` picks the winner. Verified
  with a real 2-alternative case (Tel Aviv → Jerusalem): the two OSRM alternatives had
  genuinely different accident counts (442 vs. 484) and the lower-cost one was chosen
  correctly.
- JWT-based auth (`backend/app/auth.py`, `auth_routes.py`) — bcrypt-hashed passwords,
  24h-expiry tokens, `app.users` table. Only authenticated requests can call `/api/route`.

**Not yet done:** Redis-backed rate limiting (still just `ENABLE_TEST_ENDPOINTS`-style
env-var gating for now, no actual limiter); the corridor-snapping approach from §1.4 was
replaced by the simpler accident-buffer approach above — update the report's math
description to match what's actually implemented, not the original corridor-based design.

**Constraints:**
- The `web` container has no `ports:` mapping in `compose.yaml` — only `frontend` is
  exposed to the host; `postgis` and `osrm` are reachable only from `web` over the compose
  network. Verified: `curl localhost:8000` from the host fails after this change, while the
  same request through `localhost:5173`'s proxy succeeds.
- OSRM/Nominatim timeouts degrade to 503 (`httpx.HTTPError` caught in `routing_routes.py`),
  not a crash.

### 4.2 Long-Term Memory — 10 pts

**Status: implemented.** `app.users` (`backend/app/schema.py`) stores
`driving_experience` (novice/experienced), `vehicle_type` (car/motorcycle/truck),
`avoid_tolls`, `avoid_highways` per account, set at signup and editable via
`PATCH /api/auth/me`. These feed Worker B two different ways — `avoid_tolls`/`avoid_highways`
as hard OSRM `exclude=` filters, `driving_experience`/`vehicle_type` as continuous inputs
to the `Wsafe` calculation — which is the "genuinely independent preferences, not just the
single Wsafe/Wtime knob" fix the TA's feedback asked for (§2).

**Not yet done:** the "nice to have" passive-learning idea from the original draft (nudging
preferences based on repeated route rejections) — skip it, a settings page fully satisfies
the requirement and this isn't worth the complexity given the timeline.

**Nice to have:** passive learning — e.g., if a user repeatedly rejects/edits a suggested
route in a consistent way, nudge the stored preference (skip if time-constrained; a
manual settings page fully satisfies the requirement).

### 4.3 Local LLM Integration — 10 pts

**Must have:**
- A job queue separate from (or a distinct stream within) the routing queue, feeding a
  pool of LLM worker threads/processes.
- A **fill-time heuristic**: estimate each job's expected processing time (e.g., from
  input length, whether it's a single-report classification vs. a multi-report dedup
  batch) and use that estimate to schedule/balance work across workers so no single slow
  job head-of-line-blocks fast ones. A concrete option: multiple priority queues (fast/slow)
  with workers pulling from fast first, or shortest-job-first scheduling within a worker pool.
- At least one real LLM-backed feature: hazard report triage/dedup (§1.2).
- `TESTING`/env-var gate so tests can hit LLM endpoints deterministically (mock the LLM
  call behind the flag rather than hitting the real API in CI).

### 4.4 Online Forum & Communication Suite — 10 pts

Implemented as the hazard-reporting feed from §1.1. All 8 sub-bullets from the guidelines
apply (public posting w/ media, anonymity toggle, comments w/ media, upvote/downvote +
dashboard, DMs w/ media, live notifications, rate limiting + file-size caps, cold-seeded
fake accounts/posts/threads). Real-time delivery (feed updates, DMs, notifications)
without manual refresh — WebSocket or SSE from the web gateway.

### 4.5 Deployment & CI/CD — 10 pts

- GitHub Actions (or equivalent): run the full test suite on every commit/PR.
- On main-branch green, auto-deploy to the Azure server/domain provided by the course.
- Partial credit (5 pts) is available for CI-only (tests gating, no deploy) if deployment
  proves infeasible — treat full deployment as the target, not the fallback.

---

## 5. Cross-cutting constraints (apply to all of the above)

- **Docker:** everything runs via `docker compose up` on a clean machine, first try. Take
  the course up on the Azure VM offer to verify this on a machine that isn't yours.
- **Security:** bcrypt (or equivalent) password hashing, never plaintext. Only the web
  gateway container exposes ports. Auth required before any personalized/write endpoint.
- **Persistence:** all state that matters (accounts, profiles, accident data, forum
  content, DMs) lives in PostgreSQL/PostGIS, not in memory.
- **Testing:** unit, integration, system/E2E, stress, and security tests for every
  feature you claim to have tested — no partial/fake tests (`assertEqual(x, 405)` when it
  should be 200 is an explicit example of what gets you penalized). Use an
  `ENABLE_TEST_ENDPOINTS` env var to expose test-only routes (e.g., a way to hit the LLM
  or force a worker crash) without opening them to real clients.
- **README.md:** must exist, must explain how to run the app and how to run the tests.
- **GitHub hygiene:** regular, descriptively-named commits from all three members — not
  one bulk commit at the end.
- **Grading reality check:** AI model complexity and visual design are explicitly
  **not** graded — an API call to an existing LLM is fine; don't over-invest in frontend
  polish or a fancier model than needed.

---

## 6. Open decisions / send to the TA before building

1. **Accident dataset source** — confirm and cite an actual, accessible dataset (e.g.,
   data.gov.il's road-accident datasets, or the CBS "Anatomy of severe/fatal accidents"
   series) before Worker A is built around it. This was an explicit, still-unanswered TA
   question.
2. **"Local LLM" wording** — confirm that an API-based LLM (Gemini/OpenAI/HF) satisfies
   the "Local LLM Integration" requirement, given the example `.env` in the guidelines
   already anticipates those API keys.
3. **`traffic_coverage` purpose** — this pipeline stage exists in the repo but isn't
   described in either overview doc; get a one-paragraph explanation from whoever wrote it
   (Rotem?) before the report claims anything about what it does.
4. **Forum reinterpretation** — the guidelines explicitly allow swapping a suggested
   feature for "another similar feature that tests the same concepts," but also say to
   mail the course staff about guideline changes. A quick confirmation email covering
   your hazard-reporting forum + LLM-triage choices costs nothing and removes ambiguity
   before you sink two weeks into it.

---

## 7. TODO list (phased, given the 2026-07-16 presentation and 2026-08-23 deadline)

### Phase 0 — Now → Jul 9 (stand up the new repo, port the foundation, close gaps)
- [x] Accident dataset acquired, cleaned, and geocoded (`foundation_data` + `accident_attribution`, in the foundation repo) — this resolves §6.1's blocking concern. **Correction:** actual seeded row count is **49,941** accidents, not ~30,000 as stated in the proposal — update the report to cite the real number.
- [x] Create the new project repository (private): [NetaSilam/Context_aware_routing_engine](https://github.com/NetaSilam/Context_aware_routing_engine).
- [x] Local scaffold pushed: `compose.yaml` (postgis + web), `db/init/01-load-seed.sh` (auto-restores a seed dump via `docker-entrypoint-initdb.d` if present, no-ops otherwise), `db/seed/README.md`, minimal FastAPI backend (`/health`, `/health/db`), `.env.example`, `.gitignore`, root `README.md`.
- [x] §0.1 step 1: `data/` parquet/geoparquet exports added; `backend/app/seed.py` loads them into PostGIS on first `web` startup. **Verified end-to-end** with `docker compose up --build`: `/health` and `/health/db` both return 200, all 8 tables seeded with real row counts (49,941 accidents, 362,922 corridors, 317,440 OSM roads, etc.), and re-running skips already-seeded tables (checked via a second `docker compose up`). One bug found and fixed in the process: `accident_attribution_summary`'s breakdown columns hold nested dict values that neither pandas nor psycopg can bind directly — `seed.py` now JSON-encodes those to text before insert.
- [x] Closed the `canonical_corridor_display`/`canonical_roads` gap from §0.1 by adapting rather than waiting for the missing tables: `backend/app/data_routes.py` now serves `/api/canonical-network/corridors` (bbox list), `/corridors/{id}` (detail + official segment links), `/api/accident-attribution/accidents` (bbox list), and `/accidents-attribution/summary` — all querying real seeded data, verified live (real Tel-Aviv-area corridors/accidents returned, Hebrew street names intact). Not ported: `canonical_network`'s `/summary` (needs the missing audit tables) and all of `traffic_coverage` (no data for it in this export).
- [ ] Port the remaining pieces from the foundation repo as proper `repositories/`/`services/`/`schemas/` layers (currently one flat `data_routes.py` with inline SQL) if/when `traffic_coverage` data or the audit tables become available - not urgent, current structure is fine for the MVP.
- [x] Frontend ported (`frontend/`, React/Leaflet, Canonical Network + Accident Attribution pages, Traffic Coverage dropped). Dockerized as its own service, wired to the backend via `API_PROXY_TARGET`; `web` no longer publishes a port to the host, only `frontend` does (http://localhost:5173) - closes the "only the web container is exposed to clients" gap in one move. Verified: frontend's own test suite (9 tests) + `tsc`/production build + live end-to-end render against seeded data, all pass.
- [ ] §6.2/§6.4: send the confirmation email to the TA (LLM wording + forum reinterpretation) — still open.
- [x] OSRM stood up (§1.3) - real container, Israel/Palestine graph prepared and verified (route alternatives, `exclude=motorway` confirmed to actually change the route). Nominatim **not self-hosted**: pivoted to the public API after self-hosting crashed the dev machine (out of RAM) - see §1.3's geocoding note for the full trade-off and how to switch to self-hosted later.
- [x] `compose.yaml` extended with `osrm` (internal-only). Redis/job-queue still not added - not needed yet since routing is currently synchronous request/response, not queued.
- [x] Data model added: `app.users` (driving_experience, vehicle_type, avoid_tolls, avoid_highways) - see §4.2. `RoutePreference` folded into `users` rather than a separate table (simpler, same effect). `HazardReport`/`Comment`/`Vote`/`DirectMessage`/`Notification` still not started - that's the Phase 2 forum work.

### Phase 1 — Jul 9 → Jul 16 (MVP for the presentation) — core loop done, ahead of schedule
- [x] `GET /api/geocode`: address text → candidate coordinates (§1.3, public Nominatim).
- [x] Worker A: implemented as a 30m route-buffer accident count (`accident_attribution.accident_attributions`), not corridor-matching - see §4.1 for why, update any report text that still describes the corridor-matching version.
- [x] Worker B: risk density + cost function, verified picking the correct lower-cost route between two genuinely different OSRM alternatives (Tel Aviv → Jerusalem: 442 vs. 484 accidents).
- [x] Auth: JWT login/signup/me/preferences (`backend/app/auth.py`, `auth_routes.py`), bcrypt-hashed passwords.
- [x] `POST /api/route` end-to-end with auth - verified with a real geocoded Hebrew address pair (דיזנגוף 100 תל אביב → כיכר רבין). **No rate limiting yet** (was "with the queue" in the original plan - there's no queue yet either, requests are synchronous; fine for now, revisit under Phase 3's job-queue work).
- [x] Frontend: "Plan a Route" page (`frontend/src/pages/PlanRoutePage.tsx`) - now the default/first page, with the 2 explorer pages still present as secondary tabs. Sign in/sign up, address search with disambiguation, map showing the chosen route vs. alternatives, and the stats/explanation panel.
- [ ] Manual hand-calculated sanity check on 2-3 routes vs. Waze (from TA feedback, cheap to do now while the math is fresh) - still open.
- [ ] 5-minute presentation deck - still open, but the live demo material now exists: sign up, plan a route, see the risk-aware pick.

### Phase 2 — Jul 16 → Aug 2
- [ ] Long-term memory: preference storage (tolls/highways) wired into Worker B's cost function.
- [ ] Hazard-reporting forum: posts (text/image/video), anonymity toggle, comments, upvote/downvote, profile dashboard.
- [ ] Cold-seeding script: fake users + historical hazard reports + comment threads.
- [ ] Rate limiting + file-size caps on all forum/media endpoints.
- [ ] Start unit + integration tests alongside each feature as it's built (not after).

### Phase 3 — Aug 2 → Aug 16
- [ ] DMs (text/image/video) + live notifications (WebSocket/SSE) for DMs and vote/comment activity.
- [ ] LLM job queue: worker pool, fill-time heuristic/scheduling, hazard triage & dedup feature.
- [ ] (Stretch) Route explanation LLM feature.
- [ ] CI/CD: test suite gating, auto-deploy to Azure on green main.
- [ ] `ENABLE_TEST_ENDPOINTS` gating for LLM/queue test hooks.

### Phase 4 — Aug 16 → Aug 23 (hardening + submission)
- [ ] Stress tests (burst of concurrent route/forum requests, huge request volume to one endpoint).
- [ ] Security tests (auth-gated endpoints reject unauthenticated calls; verify with real assertions, not `assertEqual(x, wrong_code)` placeholders).
- [ ] Verify the whole stack boots first-try on the Azure VM / a clean machine.
- [ ] Write the final report: app explanation, feature-by-feature test description, risk assessment (availability, scalability, spam, security).
- [ ] Record the demo video.
- [ ] Buffer for whatever breaks — do not start this phase in the last 3 days.
