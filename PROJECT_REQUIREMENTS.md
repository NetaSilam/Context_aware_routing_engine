# Context-Aware Safe Routing Engine — Requirements & Guidelines

**Course:** Software Engineering for ML (Spring 2026)
**Team:** Neta Silam (211569637), Rotem Borenstein (211620570), Yam Ben Tov (314745860)
**Foundation repo (data/mapping pipeline, reused as an input — not the project repo):** [github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine](https://github.com/RotemBorenstein/Context-Aware-Safe-Routing-Engine)
**Project repo:** not created yet — see §0.1
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

### 0.1 How this becomes the new repo

Don't re-run the heavy GIS pipeline (geopandas/shapely/PostGIS ETL) inside the new
project's Docker build — it's slow, has a large dependency footprint, and the accident
dataset is static, which works against the "runs first try on any computer" requirement.
Instead, split what gets carried over into two different things:

1. **Pipeline output → a static seed, not live code.** Run the foundation pipeline once
   (already done), then `pg_dump` the resulting PostGIS schema/tables (or export the
   pipeline's parquet artifacts) and commit that dump into the new repo, e.g.
   `db/seed/road_risk_mapper.dump`. The new repo's `postgis` service loads it via the
   official Postgres image's `docker-entrypoint-initdb.d` mechanism on first boot — one
   `docker compose up`, no pipeline re-run required. Keep the original repo around as the
   place you'd go back to if the data ever needs regenerating; link to it in the new
   repo's README for provenance, but don't depend on it at runtime or at grading time.
2. **Serving/query code → port it, it's real application code.** `backend/app/api/routes/{canonical_network,accident_attribution,traffic_coverage}.py`
   and their matching `repositories/`/`services/`/`schemas/` modules are not batch ETL —
   they're the tested, working read API this project needs to show corridor/accident data
   on the map and to feed Worker A's risk lookup (§4.1). Copy these modules into the new
   repo's backend as-is and keep their existing tests; this is the fastest path to a
   credible Jul 16 demo, since a chunk of "Core Routing Engine" scaffolding is already done.
3. **Frontend explorer pages → optional carryover.** The 3 existing map-explorer pages are
   a nice-to-have (e.g. as an admin/debug view) but not required for the core user flow
   (request a route). Port them only if time allows after the route-request UI works.

This also reshapes Phase 0 below: the "create the new GitHub repo" and "port the seed +
serving layer" steps come first, before anything else.

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
into the same risk-scoring pipeline (Worker A/B) that today only reads the static 30k
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

**Must have:**
- `POST /route`: accepts origin/destination, calls the new OSRM container (§1.3) for alternative routes + ETA.
- Worker A: snaps each OSRM route's coordinates onto the existing corridor layer (reusing
  the nearest-corridor matching already implemented in `accident_attribution/assign.py`)
  to pull historical accident counts `C(i)` per corridor; builds the user's risk context
  (experience, vehicle type, day/night).
- Worker B: computes `S(R) = ΣC(i)/ΣL(i)`, derives `Wsafe`/`Wtime` from the risk context,
  returns the route minimizing `Cost(R) = Wtime·NormalizedTime(R) + Wsafe·NormalizedRisk(R)`.
- JWT-based auth (new — doesn't exist yet); only authenticated users can request personalized routes.
- Redis-backed rate limiting on `/route` and all other client-facing endpoints.

**Constraints:**
- Workers, Redis, and MongoDB are not reachable from outside the Docker network; only the
  web gateway is exposed.
- OSM timeouts must degrade gracefully (503, not a crash).

### 4.2 Long-Term Memory — 10 pts

**Must have:**
- A persistent per-user preference record beyond the login credentials: at minimum
  `avoid_tolls`, `avoid_highways`, and the existing driving-experience/vehicle-type
  profile fields.
- Preferences feed into the Worker B cost function as hard filters or additional weighted
  terms — not just the single `Wsafe`/`Wtime` knob (this directly addresses the "single
  weight" feedback).
- Preferences are editable by the user and persist across sessions/logins.

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
  content, DMs) lives in MongoDB, not in memory.
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
- [x] Accident dataset acquired, cleaned, and geocoded (`foundation_data` + `accident_attribution`, in the foundation repo) — this resolves §6.1's blocking concern; just confirm the ~30k figure against the actual row count for the report.
- [ ] Create the new project repository (private) — this is where grading, CI/CD, and all new features live from now on.
- [ ] §0.1 step 1: `pg_dump` the foundation repo's PostGIS schema/data into a seed file; wire it into the new repo's `compose.yaml` via `docker-entrypoint-initdb.d`.
- [ ] §0.1 step 2: port `canonical_network`/`accident_attribution`/`traffic_coverage` API routes + repositories/services/schemas (and their tests) into the new repo's backend.
- [ ] §6.2/§6.4: send the confirmation email to the TA (LLM wording + forum reinterpretation) — still open.
- [ ] Add root-level `README.md` to the **new** repo with run + test instructions (mandatory per the guidelines); link back to the foundation repo for provenance of the accident/road data.
- [ ] Stand up the OSRM container from §1.3 in the new repo, against the Israel `.osm.pbf` extract the foundation repo already uses.
- [ ] New repo's `compose.yaml`: postgis (seeded) + web + redis + OSRM at minimum; decide Option A vs. B from §3 for reliable job delivery.
- [ ] Data model additions on top of the ported Postgres/PostGIS schema: User, RoutePreference, HazardReport, Comment, Vote, DirectMessage, Notification.

### Phase 1 — Jul 9 → Jul 16 (MVP for the presentation)
- [ ] Worker A: glue OSRM's route output to the existing corridor-matching logic to pull accident counts per candidate route.
- [ ] Worker B: risk density + cost function, returning a ranked route (this is the one piece of the original proposal's math that doesn't exist in the repo yet).
- [ ] Auth: JWT login/signup (new — the current API has no auth at all).
- [ ] `POST /route` end-to-end through the queue, with auth and rate limiting.
- [ ] Frontend: a 4th page — route request form (origin/destination) + map showing the chosen route, alongside the 3 existing explorer pages (visual design isn't graded, keep this thin).
- [ ] Manual hand-calculated sanity check on 2-3 routes vs. Waze (from TA feedback, cheap to do now while the math is fresh).
- [ ] 5-minute presentation deck + live demo of the MVP — the existing 3 explorer pages plus a working end-to-end route request is already a credible demo.

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
