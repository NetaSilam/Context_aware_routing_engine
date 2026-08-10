# LLM integration feature tickets

These tickets implement `docs/LLM_FEATURE_PRD.md`. They assume the foundation already built for
routing and the forum (Alembic, one-shot `initialize`, cookie auth, Celery/Redis conventions,
`docs/CODEBASE_MAP.md`'s module/testing conventions) and do not modify either.

## 1. Add LLM job schema and a physically separate Celery queue

**What to build:** The `app.llm_jobs` table, the forum posts' new nullable classification columns,
and a second Celery app/queue with its own worker Compose service — so every later ticket has
somewhere to enqueue work without sharing the routing queue.

**Blocked by:** None — can start immediately.

**Status:** done (`backend/alembic/versions/0007_llm_jobs.py`, `backend/app/llm/tasks.py`)

- [x] Alembic migration adds `app.llm_jobs` (`id`, `kind` — `triage`/`dedup_check`/
      `route_explanation`, `subject_post_id` nullable, `subject_route_job_id` nullable
      references `app.route_jobs.id`, `status`, `queue_name`, `estimated_duration_ms`, `result`
      jsonb, `error`, `created_at`, `completed_at`, plus a `CHECK` tying `kind` to which
      `subject_*` column must be set) and adds nullable `llm_hazard_type_suggested`,
      `llm_severity`, `duplicate_of_post_id` columns to `app.forum_posts` (PRD decision 3).
      `app.route_jobs` gets no new column — its explanation is merged into the existing `result`
      jsonb column it already writes candidates/chosen_index into, not the `snapshot` column,
      which holds the request inputs (PRD decision 11).
- [x] `app/llm/tasks.py` defines its own `Celery("road-risk-llm-worker", ...)` app. No static
      `task_routes` table — queue assignment happens per enqueue call once the fill-time heuristic
      lands (ticket 3); this ticket only ships the app/worker skeleton (PRD decision 2, revised
      from an earlier draft that incorrectly described static `task_routes`).
- [x] `compose.yaml` gains a Compose worker service, separate from the existing `worker` service
      (which is untouched) — **superseded by ticket 3**: this originally shipped as one
      `llm-worker` service running `-Q llm-fast,llm-slow`, later split into `llm-worker-fast`/
      `llm-worker-slow` once ticket 3's own verification proved single-worker multi-queue
      "priority" was not real (see ticket 3's status for the full story).
- [x] New `Settings` fields: `gemini_api_key` (`str | None`, genuinely optional at the Settings
      level — no cross-field validator requiring it, since ~30 existing test services never set
      `TESTING`/`GEMINI_API_KEY` and would otherwise fail to construct `Settings` at all; caught
      before implementation by checking `compose.test.yaml` directly, not assumed; see PRD
      decision 8), plus validated `llm_fast_queue_max_estimated_ms`, `llm_dedup_lookback_days`,
      `llm_dedup_radius_meters`, `llm_dedup_candidate_limit`, `llm_worker_concurrency`.
- [x] The migration and new worker service are verified against a real Docker Compose stack
      (clean boot, migration applies, `llm-worker` starts and responds to a Celery ping via
      `test_llm_stack.py`) — not just reviewed. This surfaced a real, unrelated regression: since
      `llm-worker` shares the routing worker's Redis broker, `Celery.control.inspect().ping()`
      (used by `/health/ready`'s `queue_worker` check) started replying with `llm-worker`'s pong
      even when the real routing `worker` was never started — readiness reported `200` with no
      route worker alive. Fixed in `app/health.py`'s `_queue_worker_readiness` by filtering ping
      replies to exclude any hostname containing `"llm-worker"`; proven both by manually starting/
      stopping each worker against a real Compose stack and by two new unit tests in
      `test_health.py` (fake `Celery`/`get_redis`) verified with a negative control (reverting the
      filter made both new tests fail as expected, then restored). See `docs/CODEBASE_MAP.md`'s
      "Important boundaries" for the permanent record of this constraint.

## 2. Add the Gemini client with a deterministic test-mode gate

**What to build:** `app/llm/client.py` — the one real external call this feature makes, and the
gate that keeps every automated test from ever making it for real.

**Blocked by:** 1. Add LLM job schema and a physically separate Celery queue.

**Status:** done (`backend/app/llm/client.py`, `backend/tests/test_llm_client.py`)

- [x] `classify_report(body, hazard_type, coordinates) -> TriageResult` calls Gemini's REST
      `generateContent` endpoint via `httpx.AsyncClient` when `settings.testing` is false; when
      true, returns a fixed deterministic value (`hazard_type_suggested` echoes the input,
      `severity="medium"`) without constructing a request (PRD decisions 1, 7).
- [x] `compare_for_duplicate(report_a, report_b) -> DuplicateJudgment` follows the same
      real/mocked branching. Its mock is not a dead constant: it case/whitespace-insensitively
      compares the two report bodies, so ticket 5's tests can exercise both the "confirmed
      duplicate" and "not a duplicate" paths deterministically without a real API call.
- [x] `explain_route(cost_breakdown, user_context) -> str` follows the same real/mocked branching
      (PRD decision 11) — shipped in this ticket even though ticket 7 is what wires it in, so the
      client module ships with all three call shapes together.
- [x] Response parsing validates the provider's JSON shape (`TriageResult`/`DuplicateJudgment`
      Pydantic models, plus an explicit `explanation` string check for the route-explanation call)
      and raises `LlmError` — never a raw `httpx`/`KeyError`/`ValidationError` — on malformed
      output, an HTTP error status, or an unreachable provider.
- [x] Unit tests (`test_llm_client.py`, 11 cases, no real infra) cover response parsing/validation
      against fixed sample payloads (well-formed, malformed field values, missing `candidates`,
      non-2xx status, a route explanation missing its `explanation` key) via `httpx.MockTransport`
      swapped in for the real transport, and confirm the mocked path never imports/calls anything
      network-related by monkeypatching `httpx.AsyncClient` to raise `AssertionError` if
      constructed at all — verified with a negative control (temporarily forcing the mock branch
      to fall through made that specific test fail for the right reason, then reverted).
- [x] A dedicated parametrized test asserts each of the three real-call functions raises
      `LlmNotConfiguredError` when `settings.testing` is false and `gemini_api_key` is unset —
      checked lazily inside the client (`_require_real_call_configured`), not via a `Settings`
      cross-field validator (PRD decision 8).

## 3. Add the fill-time heuristic and fast/slow queue routing

**What to build:** The scheduling logic the course guidelines explicitly grade — not a fake
heuristic that always returns the same estimate.

**Blocked by:** 1. Add LLM job schema and a physically separate Celery queue.

**Status:** done (`backend/app/llm/scheduling.py`, `backend/app/llm/service.py`,
`compose.yaml`'s `llm-worker-fast`/`llm-worker-slow`)

- [x] `estimate_duration_ms(kind, input_chars, candidate_count=0)` is a pure function: base cost +
      per-character cost for `triage`; additionally a per-candidate cost for `dedup_check` (PRD
      decision 4). `choose_queue(estimated_duration_ms, fast_queue_max_estimated_ms)` picks
      `llm-fast`/`llm-slow`.
- [x] `app/llm/service.py`'s `create_llm_job`/`enqueue_llm_job` (mirroring
      `notifications/service.py`'s `create_notification`/`publish_notification` two-phase split —
      insert inside the caller's transaction, dispatch after it commits) compute the estimate and
      queue once per job and insert them into `app.llm_jobs`. Jobs at or under
      `llm_fast_queue_max_estimated_ms` route to `llm-fast`; everything else to `llm-slow`.
- [x] Unit tests (`test_llm_scheduling.py`, 6 cases) cover the boundary (exactly at the threshold,
      just under, just over) and that a large `candidate_count` alone can push an otherwise-small
      `dedup_check` job into `llm-slow`.
- [x] An integration test (`test_llm_scheduling_stack.py`) proves the scheduling actually works,
      not just the routing decision — and in doing so **disproved the original architecture**:
      the first version enqueued one `llm-slow` job (many candidates) before three `llm-fast`
      jobs, started a single worker consuming `-Q llm-fast,llm-slow`, and expected the fast jobs
      to finish first. They did not — `celery inspect active_queues` showed both queues bound
      with no priority (`max_priority: None`), and the slow job completed before any fast job,
      proving Kombu's Redis transport does not drain multiple `-Q` queues in listed order despite
      that being the original (unverified) assumption in PRD decision 2. **Fix:** two separate
      worker processes, one per queue (`llm-worker-fast` / `llm-worker-slow` in `compose.yaml`),
      giving fast jobs OS-level isolation from a slow one instead of relying on broker-internal
      ordering. Re-verified with the corrected architecture: fast jobs consistently complete
      while the slow job is still running. `app/llm/tasks.py`'s `run_llm_job` task itself is a
      placeholder for this ticket (`time.sleep(estimated_duration_ms / 1000)` then a fixed
      `{"placeholder": True}` result) — real, since it genuinely takes proportional wall-clock
      time, but not yet dispatching to `app/llm/client.py`; tickets 4/5/7 replace the task body
      with real `classify_report`/`compare_for_duplicate`/`explain_route` calls without changing
      how a job is created, estimated, queued, or which worker consumes it.
- [x] Migration `0008_llm_jobs_relax_subject_constraint.py`: ticket 1's original constraint
      required a `subject_post_id`/`subject_route_job_id` to be present for its matching `kind`,
      which correctly rejects a mismatched subject but also rejected this ticket's legitimate
      subject-less scheduling-only jobs. Relaxed to reject only a subject column that does not
      match its kind, not absence — `test_llm_stack.py` updated to match (and to prove the
      mismatch case is still rejected using a real, existing forum post id, isolating the
      assertion from the separate foreign-key constraint).

## 4. Deliver hazard report triage on post creation

**What to build:** The first half of the real feature — every new forum post gets an
LLM-suggested `hazard_type`/`severity`.

**Blocked by:** 2. Add the Gemini client; 3. Add the fill-time heuristic.

**Status:** done (`backend/app/forum/routes.py`, `backend/app/llm/tasks.py`,
`backend/tests/test_llm_triage_stack.py`)

- [x] `create_post` (in `app/forum/routes.py`) calls `create_llm_job(connection, kind="triage",
      subject_post_id=post_id, input_chars=len(body))` inside the same transaction as the INSERT,
      then `enqueue_llm_job(job)` after it commits (same after-commit pattern as notifications,
      PRD decision 5) — wrapped in its own `try/except Exception: pass`, since a broker outage at
      that exact instant must never turn an already-successful post creation into an error
      response (the job simply stays `queued` forever rather than the request failing).
- [x] `run_llm_job` (in `app/llm/tasks.py`) now dispatches by `kind`: `triage` loads the post's
      `body`/`hazard_type`/coordinates, calls `classify_report` (via `asyncio.run`, since the
      Celery task itself is synchronous — same worker-side sync/async bridge pattern as elsewhere
      in this codebase), and writes the result onto both `llm_jobs.result` and the post's
      `llm_hazard_type_suggested`/`llm_severity` columns. `dedup_check`/`route_explanation` still
      use ticket 3's placeholder body until tickets 5/7 land.
- [x] A provider error or timeout marks the job `failed` (with the exception message, truncated)
      and leaves the post fully visible and functional, unclassified (PRD decision 6, fail-open).
      Verified with a real simulated failure, not just asserted from the code: `app/llm/client.py`
      gained a `TEST_FAILURE_MARKER` constant (mirroring `route_job_tasks.py`'s `_test_crash_once`
      convention) — when `settings.testing` is true and a report body contains that marker, the
      mock path raises instead of returning a canned result, letting an integration test exercise
      the real failure path end-to-end without needing a real provider outage.
- [x] `PostSummary` (inherited by `PostDetail`) gained nullable `llm_hazard_type_suggested`,
      `llm_severity`, `duplicate_of_post_id` fields; `create_post`'s `RETURNING` and `list_posts`/
      `get_post`/`update_post`'s `SELECT`s all select the three new columns so `_serialize_post`
      never KeyErrors — caught immediately by the existing `test_forum_routes.py` unit tests,
      whose hand-built row fixtures didn't have the new keys either, fixed alongside a new
      `test_serialize_post_includes_llm_classification_fields` test.
- [x] Integration tests (`test_llm_triage_stack.py`, verified against a real disposable stack):
      creating a post leaves it unclassified in the immediate response, then — polling
      `app.llm_jobs` directly rather than sleeping a fixed duration — its classification appears
      once the triage job completes; a post whose body carries `TEST_FAILURE_MARKER` gets a
      `failed` job but remains fully visible (in both the detail fetch and the feed) with its
      classification fields still `null`.

## 5. Deliver near-duplicate detection and flagging

**What to build:** The second half of the real feature — near-duplicate reports get flagged
instead of silently piling up.

**Blocked by:** 4. Deliver hazard report triage on post creation.

**Status:** done (`backend/app/llm/tasks.py`, `backend/tests/test_llm_dedup_stack.py`)

- [x] After a successful `triage`, `_enqueue_dedup_check_if_applicable` (in `app/llm/tasks.py`,
      called from `run_llm_job` right after `_run_triage` succeeds, wrapped in its own bare
      `try/except: pass` — dedup is enrichment on top of enrichment, so a problem here must never
      fail an already-succeeded triage job) checks whether the post has coordinates; if so it
      finds candidates via `_find_dedup_candidates`, computes the estimate/queue from the real
      (capped) candidate count, inserts the `dedup_check` row, commits, and only then calls
      `run_llm_job.apply_async(...)` — the same create-then-commit-then-dispatch ordering as the
      async FastAPI path, just written with sync `psycopg` since Celery tasks in this codebase are
      synchronous (PRD decision 5). **Note on "reusing the PostGIS pattern from `data_routes.py`"**:
      `forum_posts` has no stored PostGIS geometry column (just plain `longitude`/`latitude`
      floats), unlike the tables `data_routes.py` queries — so the distance search is computed
      on the fly via `ST_DWithin(ST_MakePoint(...)::geography, ST_MakePoint(...)::geography,
      radius)` rather than literally reusing that file's query, which assumes a stored geometry.
      This still uses the same already-enabled PostGIS extension the rest of the project relies
      on, without widening the forum schema for one feature.
- [x] `_find_dedup_candidates` bounds candidates with the SQL `LIMIT :llm_dedup_candidate_limit`
      clause directly (same value used for both the enqueue-time count and the dedup_check task's
      own re-query at execution time — the candidate set is re-fetched fresh rather than passed
      through the job, so it reflects the current state, not a stale snapshot from enqueue time).
      `_run_dedup_check` calls `compare_for_duplicate` per candidate (nearest/most-recent first)
      and stops at the first confirmed duplicate, setting `duplicate_of_post_id` — already surfaced
      in the API response since ticket 4 added the field to `PostSummary`/`PostDetail`; the post is
      never deleted or hidden.
- [x] A post with no coordinates skips dedup entirely — verified, not assumed:
      `test_a_post_with_no_coordinates_never_gets_a_dedup_check_job` asserts no `dedup_check` row
      is ever created for such a post (not just "not yet").
- [x] Integration tests (`test_llm_dedup_stack.py`, verified against a real disposable stack — a
      dedicated `llm-dedup-api`/`llm-dedup-worker-fast` pair with `LLM_DEDUP_CANDIDATE_LIMIT`
      overridden to `2`, since that setting is baked into a process's `Settings` at startup and
      testing the cap cheaply needs a small number, not exhausting the real default of 20): a
      genuine near-duplicate (same hazard type, same wording, ~15m apart) gets flagged; a
      different hazard type at the same exact spot does not; the same hazard type ~100km+ away
      does not; a post with no coordinates never gets a `dedup_check` job at all; and a dense
      cluster of 4 nearby same-hazard-type posts against a limit of 2 produces a job whose
      `result.candidates_checked == 2`, not 4 — proving the cap is enforced, not just configured.

## 6. Surface classification and duplicate flags in the frontend

**What to build:** Make ticket 4-5's output visible without requiring a page reload — the
classification/dedup flag can arrive after the post already rendered.

**Blocked by:** 4. Deliver hazard report triage on post creation; 5. Deliver near-duplicate
detection and flagging.

**Status:** done (2026-08-11) — `PostList`/`PostDetailPanel` render an inline "High/Medium/Low
severity" pill (`SEVERITY_LABELS`, from `types/forum.ts`) whenever `llm_severity` is set, and a
"Possible duplicate of report ..." line whenever `duplicate_of_post_id` is set. Neither renders
when the field is still `null` (job not yet completed, or classification legitimately absent),
matching how the rest of the forum UI already renders conditionally on nullable fields (e.g.
`is_own`).

- [x] `PostList`/`PostDetailPanel` show the suggested severity (when present) and a "possible
      duplicate of ..." indicator (when `duplicate_of_post_id` is set), following the existing
      component/typed-client conventions in `frontend/src/components/forum/`.
- [x] `types/forum.ts`/`api/forum.ts` gain the new nullable fields. `PostSummary` gained
      `llm_hazard_type_suggested: HazardType | null`, `llm_severity: Severity | null`,
      `duplicate_of_post_id: string | null` (new `Severity` type + `SEVERITY_LABELS` map added
      alongside the existing `HazardType`/`HAZARD_TYPE_LABELS` pair). `api/forum.ts` needed no
      changes — it already forwards `PostSummary`/`PostDetail` verbatim from the backend response.
- [x] Frontend tests cover both the present and absent (still-processing or never-classified)
      states: `ForumPage.test.tsx` gained tests for severity-present and duplicate-present in
      both the feed list and the detail panel, plus an explicit assertion that neither renders
      for the (default, all-`null`) base fixture.

**Scope note:** the ticket's "What to build" prose mentions the classification "can arrive after
the post already rendered," but the concrete checklist above does not ask for live polling/push
updates, and the existing app has no push channel for forum posts (unlike route jobs, which do
poll). Implementing that was treated as out of scope here — it would need a new polling or SSE
mechanism applied to the whole feed, which is a real design decision, not a natural extension of
this ticket's 3 checklist items. In practice, a freshly-arrived classification becomes visible on
the next natural feed fetch (closing a report detail already calls `loadFeed`, as does changing
the hazard-type filter or loading more), just not while a user is staring at an unchanged feed
screen. If live-refresh is wanted, it should be scoped as its own ticket.

**Verified:** `npx tsc --noEmit`, `npx vitest run` (66/66, all suites) locally, then rebuilt and
ran the `frontend-tests` service against a real disposable Compose stack (`docker compose ...
run --rm --no-deps frontend-tests`, project `llm-t6-verify`) — build, typecheck, and full vitest
suite all passed inside the container, matching CI's actual execution path.

## 7. Deliver route explanation on route job completion

**What to build:** The second real LLM-backed feature — a plain-language "why you got this route"
explanation attached to every completed route job.

**Blocked by:** 2. Add the Gemini client.

**Status:** done (2026-08-11)

- [x] The route job Celery task (`route_job_tasks.py`) enqueues a `route_explanation` LLM job
      immediately after writing the job's `completed` row, passing the chosen candidate's cost
      breakdown and the user's scoring context as task arguments (PRD decision 11) — never before
      that row is written, and never blocking the route job's own completion.
      `_enqueue_route_explanation_if_possible` finds the chosen candidate in the in-memory
      `result["candidates"]` by matching `candidate_index` (not by list position — the two are
      not guaranteed to coincide), builds `cost_breakdown`/`user_context` per decision 11, and
      calls the new `app.llm.tasks.enqueue_route_explanation`. The call site is wrapped in a bare
      `try/except: pass`, same as `_enqueue_dedup_check_if_applicable` in ticket 5.
- [x] `run_llm_job`'s `route_explanation` dispatch (consumed by `llm-worker-fast`, per PRD
      decision 12 — reuses the fast queue) calls `explain_route`, then merges the result
      into `route_jobs.result` (the column `_calculate_result` already populates with candidates/
      chosen_index) via `result || jsonb_build_object('llm_explanation', ...)` — not the
      `snapshot` column, and no new column. `run_llm_job` gained an optional `extra_input` kwarg
      (only `route_explanation` uses it) so the cost breakdown/user context can be passed as real
      Celery task arguments per decision 11, instead of re-querying like triage/dedup_check do.
      The now-fully-dead `_run_placeholder` (ticket 3's temporary stand-in for this exact kind)
      was deleted along with the `else` branch that dispatched to it — all three `Kind` values
      have real handlers now.
- [x] A provider error or timeout leaves the route job's existing fields (candidates, chosen
      index, cost breakdown) fully intact; `llm_explanation` is simply absent (PRD decision 6/11,
      fail-open) — verified with the mock simulating a failure, not just asserted from the code.
- [x] Route job GET/history response models expose a nullable `llm_explanation` field read from
      `result`. Added to both `RouteJobStatus` (used by `GET /api/route-jobs/{id}` and
      `GET /api/route-history/{id}`) and `RouteHistorySummary` (`GET /api/route-history`).
- [x] Integration test: `tests/test_llm_route_explanation_stack.py`, two tests — a real HTTP
      submit-and-poll happy path, and a fail-open test that calls `enqueue_route_explanation`
      directly against a fixture route job (mirroring ticket 3's direct-function-call pattern,
      since the real `cost_breakdown`/`user_context` are computed numbers/enums with no
      HTTP-reachable free-text channel to embed `TEST_FAILURE_MARKER` in, unlike forum triage/
      dedup's report body).

**Real bugs found and fixed during verification (not just asserted from the code):**

1. **`jsonb_build_object` couldn't infer its parameter's type.** The first real run against the
   disposable stack failed every `route_explanation` job with
   `could not determine data type of parameter $1` — Postgres cannot infer a type for an
   anonymous placeholder passed into a polymorphic function like `jsonb_build_object(key, $1)`
   over the extended query protocol psycopg uses. Fixed with an explicit
   `jsonb_build_object('llm_explanation', %s::text)` cast. This is the negative control for this
   ticket: the integration test failed for a real reason, got fixed, and the fix was verified by
   re-running the same test, rather than needing an artificial break/revert cycle.
2. **`test_llm_scheduling_stack.py` (ticket 3) silently broke back at ticket 4/5 and nobody
   noticed until now.** That test's "slow job" premise depended on `_run_placeholder`'s
   `time.sleep(estimated_duration_ms / 1000)` to actually take longer than the fast jobs. Once
   ticket 4 gave `kind="triage"` a real dispatch (`_run_triage`), the test's subject-less fast
   jobs started hitting `LookupError: forum post None no longer exists` and failing outright —
   this ticket's full regression pass (running every existing `llm-*-tests`/`route-job-tests`
   service, not just the new one) is what caught it, since ticket 4/5/6's own verification only
   re-ran each ticket's own new test file, not the full suite. The deeper issue: once every
   `Kind` has real, mock-backed dispatch, every mock LLM call is effectively instant by design
   (`TESTING=true` exists so tests run fast) — there is no longer a way to make one job's real
   processing time exceed another's. Rewrote the test to prove queue isolation structurally
   instead of racing wall-clock time: only the `llm-fast` worker is started while asserting the
   fast jobs complete; the slow job is asserted to still be `'queued'` (not just "not yet
   completed") since literally no consumer exists for `llm-slow` at that point. A `llm-slow`
   worker is then started as a sanity check that the slow job isn't broken, just deprioritized.
   Also gave the test's jobs a real seeded `subject_post_id` (real dispatch now requires one for
   `triage`/`dedup_check`).

**Verified:** ran `tests/test_llm_route_explanation_stack.py` against the real disposable stack,
then re-ran the full existing regression set (`route-job-tests`, `route-history-tests`,
`llm-stack-tests`, `llm-scheduling-tests`, `llm-triage-tests`, `llm-dedup-tests`, `unit-tests`) —
all green after the two fixes above.

## 8. Surface the route explanation in the frontend

**What to build:** Make ticket 7's output visible on the route result the user is already looking
at, without requiring a page reload.

**Blocked by:** 7. Deliver route explanation on route job completion.

**Status:** ready-for-agent

- [ ] `PlanRoutePage`'s result panel shows the explanation text when present, and shows nothing
      extra (not a loading spinner blocking the rest of the result) when it is still processing or
      failed — the numeric breakdown and map are never gated on it.
- [ ] Route job/history types and API client gain the new nullable field.
- [ ] Frontend tests cover both the present and absent states, matching ticket 6's approach for
      forum classification.

## 9. Extend security and stress validation to the LLM queue

**What to build:** Prove this feature meets the same bar as everything else in the repo, per PRD
Testing Decisions 5 and 7, before calling it done.

**Blocked by:** 4. Deliver hazard report triage on post creation; 5. Deliver near-duplicate
detection and flagging; 7. Deliver route explanation on route job completion.

**Status:** ready-for-agent

- [ ] A test proves `GEMINI_API_KEY` never appears in process output, mirroring
      `test_forum_security_stack.py`'s `capfd`-based proof for forum/DM content.
- [ ] A test proves every automated test environment runs with `settings.testing = true` (no
      accidental real API call from CI).
- [ ] The Locust stress profile gets tasks creating hazard reports and route jobs at a higher rate
      than usual, asserting the `llm-fast`/`llm-slow` queues stay bounded (no unbounded growth, no
      worker crash) under load, consistent with `docs/forum-feature-tickets.md` ticket 9's stress
      extension.
- [ ] `docs/CODEBASE_MAP.md` and `docs/DOCUMENTATION_GUIDE.md` are updated to list the new `llm`
      module, table, worker service, and tests.
- [ ] This ticket file's own per-ticket `**Status:**` lines serve as the feature-to-test matrix,
      matching the convention already established for the forum vertical.
