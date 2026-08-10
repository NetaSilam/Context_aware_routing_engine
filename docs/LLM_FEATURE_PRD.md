# LLM Integration Feature PRD

## Problem Statement

The course guidelines require a "Local LLM Integration" component (`Proj_Guidelines.pdf`,
`PROJECT_REQUIREMENTS.md` §4.3, 10 pts): a job queue **separate from** the routing queue feeding
a worker pool, a **fill-time heuristic** that estimates each job's processing time and uses that
estimate to schedule work so a slow job cannot head-of-line-block fast ones, at least one real
LLM-backed feature, and a `TESTING`-style gate so automated tests never depend on a live external
API call. None of this exists in the codebase yet — verified directly (no `logging`-adjacent
grep noise this time, a direct search for `llm|openai|gemini|anthropic|huggingface` across
`backend/app/` returns nothing real).

`PROJECT_REQUIREMENTS.md` §1.2 recommends **hazard report triage & dedup** as the primary
feature: free-text forum reports get classified into `{hazard_type, severity}`, and near-duplicate
reports about the same spot get flagged instead of letting ten posts pile up about one pothole.
This is the feature the mandatory fill-time heuristic is built and tested against, since report
length and dedup-batch size genuinely vary in a way that gives the heuristic something real to do.

**Scope decision (2026-08-10, revised):** the secondary **route explanation** feature — turning
`route_scoring_service.py`'s numeric cost breakdown (`Wsafe`/`Wtime`, normalized risk, the chosen
candidate's historical accident density) into a one-paragraph plain-language "why you got this
route" explanation — is **in scope**, added after the original triage/dedup-only decision. It
reuses the same Gemini client, the same `settings.testing` gate, and (for consistency and latency
isolation, even though the job-queue requirement is already satisfied by triage/dedup)
the same `llm-fast` queue as triage, rather than blocking route-job completion synchronously.

**Provider decision (2026-08-10):** Google Gemini — a real `GEMINI_API_KEY` is now set in the
local, gitignored `.env` (confirmed present and non-placeholder; never printed or committed).
Called via plain `httpx` (already a project dependency, already the pattern used for OSRM/
Nominatim) rather than adding the `google-generativeai` SDK as a new dependency for two REST call
shapes.

**Open item, not a blocker:** `PROJECT_REQUIREMENTS.md` §6.2 notes that "Local LLM Integration"
wording should ideally be confirmed with course staff as satisfied by an API-based provider rather
than self-hosted weights. The example `.env` in the guidelines already anticipates API keys, so
this PRD proceeds on that reading; flag it in the final report regardless.

This feature must reuse existing conventions rather than inventing new ones: Alembic-owned schema,
FastAPI routers where an endpoint is needed, Celery/Redis for async work (already used by routing),
and the `settings.testing`-gated pattern already used for the routing test-scoring router
(`app/main.py`) — extended here to gate the LLM client's real network call, not just a route.

## Solution

- New `backend/app/llm/` module, structured like `forum/`/`messaging/`/`notifications/`.
- A **second, physically separate Celery queue** (`llm`), not a second task type sharing the
  routing queue — a dedicated `llm-worker` Compose service consumes it, distinct from the existing
  `worker` service. Same Redis broker; queue separation is what the requirement asks for, not a
  second broker.
- A new `app.llm_jobs` table (Alembic migration) tracking each classification job's status, input
  size, estimated duration, assigned queue, result, and error — so the fill-time heuristic has a
  real record to schedule against, not just an in-memory guess, and so a forum post's
  classification state survives a worker restart.
- **Fill-time heuristic:** estimate a job's duration from its input size (single report body vs. a
  dedup-comparison batch against N nearby recent reports), and route it into one of two queues —
  `llm-fast` (single-report classification) or `llm-slow` (dedup comparison batches) — consumed by
  workers that drain fast first. This is the "estimate → schedule" requirement made concrete and
  testable, not a fake heuristic that always returns the same number.
- **Trigger:** after `create_post` commits (same after-the-transaction pattern already used for
  notifications — see `FORUM_FEATURE_PRD.md` decision 14), enqueue a triage job referencing the
  new post. The forum feature itself is not modified beyond this one enqueue call plus new
  response fields; no change to anonymity, voting, or media handling.
- **Gemini client** (`app/llm/client.py`) wraps three REST call shapes: given a report's body +
  hazard type + optional location, return `{hazard_type_suggested, severity}`; for a dedup check,
  a yes/no/confidence judgment against a candidate report's text; for route explanation, a
  cost-breakdown + user profile in, a one-paragraph explanation string out. Gated by
  `settings.testing`: when true (always true in the test/CI environment), the client returns a
  deterministic canned response and makes no network call at all — not just a stubbed HTTP layer,
  the client function itself branches before ever constructing a request.
- **Route explanation trigger:** when a route job's Celery task (`route_job_tasks.py`) finishes
  writing the job's `completed` row, it enqueues a `route_explanation` LLM job carrying the chosen
  candidate's cost breakdown and the user's scoring context directly as task arguments (not
  re-derived from the database by the LLM worker, to keep the LLM module decoupled from routing's
  internal result shape). The `llm-worker` calls `explain_route`, then merges the result into the
  existing `route_jobs.result` JSONB — the column the worker already writes `candidates`/
  `chosen_index`/`safety_weight`/`time_weight` into (`route_job_tasks.py`'s `_calculate_result`) —
  via `result || jsonb_build_object('llm_explanation', ...)`. No new column on `route_jobs`, and
  note `route_jobs.snapshot` is a *different* existing column (the request inputs at submission
  time, written once before scoring runs) — the explanation must not be merged into that one.

## User Stories

1. As a driver reporting a hazard, I want my free-text report automatically tagged with a
   severity level, so that other drivers can triage which reports matter most without reading
   every one in full.
2. As a driver browsing the feed, I want near-duplicate reports about the same hazard merged or
   flagged, so that the feed does not fill up with ten posts about one pothole.
3. As the system, I want classification work queued separately from route-scoring work, so that a
   burst of forum activity cannot delay someone's route job, and vice versa.
4. As the system, I want a single large dedup-comparison batch to never block a wave of fast
   single-report classifications behind it in the same queue.
5. As a developer, I want every automated test to run against a deterministic mocked LLM response,
   so the suite is fast, free, and never flaky because of an external provider's latency or quota.
6. As a user, I want the system to keep working normally if the LLM provider is unreachable or
   errors — my report still posts and stays visible, just without a suggested classification.
7. As a driver who just got a route, I want a short plain-language reason for why this route was
   chosen over the alternatives, so the numeric cost/risk breakdown is not the only explanation
   offered.
8. As a user, I want my route result to keep working exactly as it does today if the explanation
   is still processing or fails — the route, its candidates, and its numeric breakdown are never
   gated on the LLM call succeeding.

## Implementation Decisions

1. **Provider and transport.** Google Gemini via `httpx.AsyncClient` calling the REST
   `generateContent` endpoint directly — no new SDK dependency, consistent with how
   `geocoding/client.py` calls Nominatim and `routing/osrm_client.py` calls OSRM.
2. **Queue separation.** `app/llm/tasks.py` defines its own `Celery("road-risk-llm-worker", ...)`
   app (mirroring `route_job_tasks.py`'s `celery_app`) with `task_routes` sending everything to
   `llm-fast` or `llm-slow` queues. A new `llm-worker` Compose service runs
   `celery -A app.llm.tasks.celery_app worker -Q llm-fast,llm-slow --loglevel=INFO` (queue order
   matters — Celery drains listed queues in order, giving fast jobs priority). The existing
   `worker` service is untouched and continues to own only the routing queue.
3. **Schema.** `app.llm_jobs`: `id (uuid)`, `kind` (`triage` | `dedup_check` | `route_explanation`),
   `subject_post_id` (nullable — unused for `route_explanation`), `subject_route_job_id` (nullable
   — unused for `triage`/`dedup_check`, references `app.route_jobs.id`), `status`
   (`queued` | `running` | `completed` | `failed`), `queue_name`, `estimated_duration_ms`, `result`
   (jsonb, nullable), `error` (text, nullable), `created_at`, `completed_at`. Forum posts gain
   nullable `llm_hazard_type_suggested`, `llm_severity`, `duplicate_of_post_id` columns rather than
   requiring a join for the common read path (the feed already reads denormalized counters the
   same way — see `FORUM_FEATURE_PRD.md`'s posts table). `route_jobs` gains **no new column**;
   its explanation lives inside the existing `result` JSONB (decision 11 below) — not `snapshot`,
   which is a different existing column holding the request inputs, not the scored output.
4. **Fill-time heuristic.** `estimate_duration_ms(kind, input_chars, candidate_count)` is a pure
   function: a fixed base cost plus a per-character cost for `triage`, and additionally a
   per-candidate cost for `dedup_check` (since a dedup job compares against `candidate_count`
   nearby reports, not just one). Jobs at or under
   `llm_fast_queue_max_estimated_ms` (a validated `Settings` field, default tuned so ordinary
   single-report triage always qualifies) go to `llm-fast`; everything else goes to `llm-slow`.
   This is deliberately simple and testable — no ML-based estimation, matching this project's
   general "explainable, not clever" bias (see `ROUTING_FEATURE_PRD.md`'s scoring philosophy).
5. **Dedup scope.** A dedup check only compares a new report against *other active reports of the
   same `hazard_type`* created in the last `llm_dedup_lookback_days` (default 14) within
   `llm_dedup_radius_meters` (default 150m) of the new report's coordinates — reusing the same
   PostGIS distance-query pattern already used elsewhere (`data_routes.py`'s bbox queries), not a
   new spatial primitive. If the new report has no coordinates, dedup is skipped entirely (nothing
   to compare against) rather than falling back to a citywide or title-text-only match.
6. **Fail-open, not fail-closed.** Unlike rate limiting (`ROUTING_FEATURE_PRD.md`/
   `FORUM_FEATURE_PRD.md`'s fail-closed `503` behavior for a Redis outage), an LLM provider error
   or timeout marks the job `failed` and leaves the post exactly as created — visible, unclassified,
   not duplicate-flagged. Classification is enrichment, not a security or abuse control, so
   availability wins over completeness here. This is a deliberate, different tradeoff from the
   forum's existing fail-closed writes — call this out explicitly in the report's risk-assessment
   section rather than presenting one fail-mode philosophy as universal.
7. **Testing gate.** `settings.testing` (the same field already gating
   `app/routing/test_scoring_router.py`'s registration in `main.py`) gates
   `app/llm/client.py`'s real HTTP call: when true, `classify_report`/`compare_for_duplicate`
   return fixed, deterministic values without constructing a request. All Compose test services
   set `TESTING: "true"`, matching the existing `worker` service's test environment.
8. **Configuration.** New validated `Settings` fields: `gemini_api_key` (`str | None`, required
   only when `testing` is false — enforced by a `model_validator`, not a runtime `None` check
   scattered through the client), `llm_fast_queue_max_estimated_ms`, `llm_dedup_lookback_days`,
   `llm_dedup_radius_meters`, `llm_worker_concurrency`. Same pattern as every other feature's
   settings block in `config.py` — no committed usable defaults for the secret.
9. **Anonymity boundary.** The LLM never receives author identity — only report body, hazard type,
   and coordinates are sent, regardless of `is_anonymous`. This is not a new anonymity mechanism;
   it is simply that classification never needed author identity in the first place, so there is
   no new leak surface to reason about (`is_anonymous` continues to control only API-response
   visibility, per the existing invariant in `FORUM_FEATURE_PRD.md`).
10. **No re-classification on edit.** Editing a post's body does not re-trigger triage/dedup in
    v1 — avoids a whole class of "stale classification vs. edited content" bugs for a feature
    that is enrichment, not load-bearing. Worth a "future work" mention, not worth building now.
11. **Route explanation trigger and storage.** The route job Celery task enqueues a
    `route_explanation` LLM job immediately after it writes the job's `completed` row (not
    before — the explanation must describe a route that was actually chosen, and must never delay
    or block the route result the user is waiting on). `explain_route` receives the chosen
    candidate's `duration_seconds`, `historical_accident_density_per_km`, `final_cost` breakdown,
    and the user's `driving_experience`/`vehicle_type`/time-of-day context — the same inputs
    `route_scoring_service.py` already computed, passed as task arguments, not re-queried. The
    `llm-worker` writes the result back with
    `UPDATE app.route_jobs SET result = result || jsonb_build_object('llm_explanation', :text) WHERE id = :id`
    — merging into the `result` column the worker already populates with `candidates`/
    `chosen_index`/etc. (`route_job_tasks.py`'s `_calculate_result`), not the `snapshot` column
    (that one holds the request inputs, unrelated to the scored output). Same fail-open behavior
    as decision 6: a failed/errored explanation job leaves `llm_explanation` absent from `result`;
    the route result is complete and usable without it.
12. **Route explanation reuses the fast queue.** A single explanation call has the same rough cost
    shape as a single triage call (one document in, one short document out) — `estimate_duration_ms`
    classifies it the same way triage is classified, so it does not need a third queue.

## Testing Decisions

1. **Primary testing seam.** The public effect of posting a hazard report: a classification
   eventually appears on the post, and a genuine near-duplicate gets flagged — verified end-to-end
   against a real disposable Postgres/Redis/Celery stack with the LLM client mocked via
   `settings.testing`, matching every other feature's integration-test convention in this repo.
2. **Unit coverage.** `estimate_duration_ms`'s fast/slow routing boundary (pure function, no
   database), and the Gemini response-parsing/validation logic (given a fixed sample JSON payload,
   independent of whether the call was real or mocked).
3. **Integration coverage.** Real Postgres/Redis/Celery, LLM client mocked: job creation → correct
   queue assignment → worker consumption → post updated with a classification; a genuine
   near-duplicate scenario (two reports, same hazard type, close in space and time) gets flagged;
   a non-duplicate scenario (different hazard type or far apart) does not; a simulated provider
   error leaves the post fully functional and unclassified (fail-open, decision 6).
4. **Scheduling proof.** A dedicated test asserting that a `llm-slow` (dedup, many candidates) job
   enqueued before several `llm-fast` (triage) jobs does not delay them — the fast jobs' results
   are observable before the slow job's, proving priority queue draining actually works rather
   than asserting it by code inspection alone.
5. **Security coverage.** No automated test ever makes a real network call to Gemini (verified by
   asserting `settings.testing` is true in every test environment and, like the forum's log-content
   proof in `FORUM_FEATURE_PRD.md`, a dedicated check that `GEMINI_API_KEY` never appears in
   process output). Cross-user isolation: a dedup flag on user A's post never exposes user B's
   post body beyond what the feed already shows publicly (forum posts are not private content).
6. **Fake LLM in tests.** Tests use the `settings.testing` deterministic-response path, never a
   real API key or a live HTTP mock server — faster and with zero external dependency, consistent
   with how `fake_osrm`/`fake_geocoder` exist as real HTTP doubles for *those* upstreams but an
   in-process branch is simpler and sufficient here since there is exactly one call shape.
7. **Route explanation coverage.** A completed route job eventually gets a non-empty
   `llm_explanation` in its `result` (mocked client, real Celery/Postgres); a simulated provider
   failure leaves the route job's existing fields (candidates, chosen index, cost breakdown) fully
   intact and `llm_explanation` simply absent — the route result was never gated on this call.

## Out of Scope

- Self-hosted/local model weights — API-based integration is the accepted reading of "Local LLM
  Integration" for this project (see the open item above).
- Multi-provider fallback (Gemini down → try OpenAI) — one provider is sufficient for the
  requirement; revisit only if Gemini's free tier proves unusable during grading.
- Re-classification on post edit.
- Feeding LLM-derived severity into the routing risk score — same reasoning as
  `FORUM_FEATURE_PRD.md`'s decision to keep the hazard forum separate from the immutable,
  versioned routing risk data; LLM output is even less suited to feed a scoring pipeline than raw
  unmoderated reports would be.
- Image-based classification (the guidelines' §1.2 mentions "optionally image" — v1 is text-only;
  forum posts already support image/video media, so this can be added later without a schema
  change to the media side).
