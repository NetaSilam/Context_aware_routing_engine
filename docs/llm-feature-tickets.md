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

**Status:** ready-for-agent

- [ ] `create_post` (in `app/forum/routes.py`) enqueues a `triage` job referencing the new post
      after its transaction commits (same after-commit pattern as notifications, PRD decision 5).
- [ ] `run_llm_job`'s `triage` dispatch (consumed by `llm-worker-fast`, per ticket 3's estimate —
      a single report is always a fast job) calls `classify_report`, writes the result onto
      `llm_jobs`/the post's new columns, and marks the job `completed`.
- [ ] A provider error or timeout marks the job `failed` and leaves the post fully visible and
      functional, unclassified (PRD decision 6, fail-open) — verified with the mock simulating a
      failure, not just asserted from the code.
- [ ] `PostDetail`/`PostSummary` API responses include the new nullable classification fields.
- [ ] Integration test: create a post, wait for the triage job to complete against the real
      disposable stack, assert the post's classification fields are populated from the (mocked)
      response.

## 5. Deliver near-duplicate detection and flagging

**What to build:** The second half of the real feature — near-duplicate reports get flagged
instead of silently piling up.

**Blocked by:** 4. Deliver hazard report triage on post creation.

**Status:** ready-for-agent

- [ ] After a successful triage, if the post has coordinates, enqueue a `dedup_check` job that
      finds candidate posts of the same `hazard_type` within `llm_dedup_radius_meters` and
      `llm_dedup_lookback_days` (PRD decision 5), reusing the existing PostGIS distance-query
      pattern from `data_routes.py`.
- [ ] For each candidate (bounded — cap the candidate count so one dense area cannot create an
      unbounded job), call `compare_for_duplicate`; on a confirmed duplicate, set
      `duplicate_of_post_id` and surface that in the API response rather than deleting the post.
- [ ] A post with no coordinates skips dedup entirely (PRD decision 5) — verified, not assumed.
- [ ] Integration tests cover: a genuine near-duplicate (same hazard type, close in space/time)
      gets flagged; a different hazard type at the same spot does not; the same hazard type far
      away does not; a candidate-count cap is actually enforced against a dense cluster of
      existing posts.

## 6. Surface classification and duplicate flags in the frontend

**What to build:** Make ticket 4-5's output visible without requiring a page reload — the
classification/dedup flag can arrive after the post already rendered.

**Blocked by:** 4. Deliver hazard report triage on post creation; 5. Deliver near-duplicate
detection and flagging.

**Status:** ready-for-agent

- [ ] `PostList`/`PostDetailPanel` show the suggested severity (when present) and a "possible
      duplicate of ..." indicator (when `duplicate_of_post_id` is set), following the existing
      component/typed-client conventions in `frontend/src/components/forum/`.
- [ ] `types/forum.ts`/`api/forum.ts` gain the new nullable fields.
- [ ] Frontend tests cover both the present and absent (still-processing or never-classified)
      states, consistent with how other async/eventually-consistent UI state is tested elsewhere
      in this codebase (e.g. the notification indicator's mocked `EventSource`).

## 7. Deliver route explanation on route job completion

**What to build:** The second real LLM-backed feature — a plain-language "why you got this route"
explanation attached to every completed route job.

**Blocked by:** 2. Add the Gemini client.

**Status:** ready-for-agent

- [ ] The route job Celery task (`route_job_tasks.py`) enqueues a `route_explanation` LLM job
      immediately after writing the job's `completed` row, passing the chosen candidate's cost
      breakdown and the user's scoring context as task arguments (PRD decision 11) — never before
      that row is written, and never blocking the route job's own completion.
- [ ] `run_llm_job`'s `route_explanation` dispatch (consumed by `llm-worker-fast`, per PRD
      decision 12 — reuses the fast queue) calls `explain_route`, then merges the result
      into `route_jobs.result` (the column `_calculate_result` already populates with candidates/
      chosen_index) via `result || jsonb_build_object('llm_explanation', ...)` — not the
      `snapshot` column, and no new column.
- [ ] A provider error or timeout leaves the route job's existing fields (candidates, chosen
      index, cost breakdown) fully intact; `llm_explanation` is simply absent (PRD decision 6/11,
      fail-open) — verified with the mock simulating a failure, not just asserted from the code.
- [ ] Route job GET/history response models expose a nullable `llm_explanation` field read from
      `result`.
- [ ] Integration test: submit a route job against the real disposable stack, wait for it to
      complete, then wait for the (mocked) explanation to appear in the same job's `result`.

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
