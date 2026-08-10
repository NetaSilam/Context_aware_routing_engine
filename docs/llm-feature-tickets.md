# LLM integration feature tickets

These tickets implement `docs/LLM_FEATURE_PRD.md`. They assume the foundation already built for
routing and the forum (Alembic, one-shot `initialize`, cookie auth, Celery/Redis conventions,
`docs/CODEBASE_MAP.md`'s module/testing conventions) and do not modify either.

## 1. Add LLM job schema and a physically separate Celery queue

**What to build:** The `app.llm_jobs` table, the forum posts' new nullable classification columns,
and a second Celery app/queue with its own worker Compose service — so every later ticket has
somewhere to enqueue work without sharing the routing queue.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Alembic migration adds `app.llm_jobs` (`id`, `kind` — `triage`/`dedup_check`/
      `route_explanation`, `subject_post_id` nullable, `subject_route_job_id` nullable
      references `app.route_jobs.id`, `status`, `queue_name`, `estimated_duration_ms`, `result`
      jsonb, `error`, `created_at`, `completed_at`) and adds nullable `llm_hazard_type_suggested`,
      `llm_severity`, `duplicate_of_post_id` columns to `app.forum_posts` (PRD decision 3).
      `app.route_jobs` gets no new column — its explanation lives in the existing `snapshot`
      jsonb (PRD decision 11).
- [ ] `app/llm/tasks.py` defines its own `Celery("road-risk-llm-worker", ...)` app with
      `task_routes` sending work to `llm-fast`/`llm-slow` queues (PRD decision 2).
- [ ] `compose.yaml` gains an `llm-worker` service running
      `celery -A app.llm.tasks.celery_app worker -Q llm-fast,llm-slow`, separate from the existing
      `worker` service, which is untouched.
- [ ] New validated `Settings` fields: `gemini_api_key` (required unless `testing`),
      `llm_fast_queue_max_estimated_ms`, `llm_dedup_lookback_days`, `llm_dedup_radius_meters`,
      `llm_worker_concurrency` (PRD decision 8).
- [ ] The migration and new worker service are verified against a real Docker Compose stack
      (clean boot, migration applies, `llm-worker` starts and can be pinged), not just reviewed.

## 2. Add the Gemini client with a deterministic test-mode gate

**What to build:** `app/llm/client.py` — the one real external call this feature makes, and the
gate that keeps every automated test from ever making it for real.

**Blocked by:** 1. Add LLM job schema and a physically separate Celery queue.

**Status:** ready-for-agent

- [ ] `classify_report(body, hazard_type, coordinates) -> {hazard_type_suggested, severity}` calls
      Gemini's REST `generateContent` endpoint via `httpx.AsyncClient` when `settings.testing` is
      false; when true, returns a fixed deterministic value without constructing a request (PRD
      decisions 1, 7).
- [ ] `compare_for_duplicate(report_a, report_b) -> {is_duplicate, confidence}` follows the same
      real/mocked branching.
- [ ] `explain_route(cost_breakdown, user_context) -> str` follows the same real/mocked branching
      (PRD decision 11) — added in this ticket even though ticket 7 is what wires it in, so the
      client module ships with all three call shapes together.
- [ ] Response parsing validates the provider's JSON shape and raises a typed error on malformed
      output rather than propagating a raw parse exception.
- [ ] Unit tests cover response parsing/validation against fixed sample payloads, and confirm the
      mocked path never imports/calls anything network-related (importing `httpx`'s transport is
      not exercised when `settings.testing` is true).
- [ ] A dedicated test asserts `GEMINI_API_KEY` is required (config validation fails closed) when
      `testing` is false and the key is unset.

## 3. Add the fill-time heuristic and fast/slow queue routing

**What to build:** The scheduling logic the course guidelines explicitly grade — not a fake
heuristic that always returns the same estimate.

**Blocked by:** 1. Add LLM job schema and a physically separate Celery queue.

**Status:** ready-for-agent

- [ ] `estimate_duration_ms(kind, input_chars, candidate_count=0)` is a pure function: base cost +
      per-character cost for `triage`; additionally a per-candidate cost for `dedup_check` (PRD
      decision 4).
- [ ] Jobs at or under `llm_fast_queue_max_estimated_ms` route to `llm-fast`; everything else to
      `llm-slow`.
- [ ] Unit tests cover the boundary (exactly at the threshold, just under, just over) and that a
      large `candidate_count` alone can push an otherwise-small job into `llm-slow`.
- [ ] An integration test proves the scheduling actually works, not just the routing decision:
      enqueue one `llm-slow` job (many candidates) before several `llm-fast` jobs, and assert the
      fast jobs' results are observable before the slow job's (PRD Testing Decision 4) — run
      against the real `llm-worker` service.

## 4. Deliver hazard report triage on post creation

**What to build:** The first half of the real feature — every new forum post gets an
LLM-suggested `hazard_type`/`severity`.

**Blocked by:** 2. Add the Gemini client; 3. Add the fill-time heuristic.

**Status:** ready-for-agent

- [ ] `create_post` (in `app/forum/routes.py`) enqueues a `triage` job referencing the new post
      after its transaction commits (same after-commit pattern as notifications, PRD decision 5).
- [ ] The `llm-worker`'s triage task calls `classify_report`, writes the result onto
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
      immediately after writing the job's `completed` snapshot, passing the chosen candidate's
      cost breakdown and the user's scoring context as task arguments (PRD decision 11) — never
      before the snapshot is written, and never blocking the route job's own completion.
- [ ] The `llm-worker`'s `route_explanation` task calls `explain_route`, then merges the result
      into `route_jobs.snapshot` via `snapshot || jsonb_build_object('llm_explanation', ...)` — no
      new column.
- [ ] A provider error or timeout leaves the route job's existing fields (candidates, chosen
      index, cost breakdown) fully intact; `llm_explanation` is simply absent (PRD decision 6/11,
      fail-open) — verified with the mock simulating a failure, not just asserted from the code.
- [ ] Route job GET/history response models expose a nullable `llm_explanation` field read from
      the snapshot.
- [ ] Integration test: submit a route job against the real disposable stack, wait for it to
      complete, then wait for the (mocked) explanation to appear in the same job's snapshot.

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
