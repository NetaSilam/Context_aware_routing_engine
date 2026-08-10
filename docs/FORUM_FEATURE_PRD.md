# Forum Feature PRD

## Problem Statement

The course guidelines require an "Online Forum & Communication Suite": public posting with
media, an anonymity toggle, commenting with media, upvote/downvote engagement with a profile
dashboard, direct messaging with media, live in-app notifications, spam/storage abuse defense,
and cold-seeded demo data (`Proj_Guidelines.pdf` §4). None of this exists in the codebase yet.

`PROJECT_REQUIREMENTS.md` §1.1 already reframes the forum as a **crowd-sourced hazard-reporting
feed** (potholes, flooding, broken signals, poor lighting, illegal speed bumps, recent crashes)
rather than a generic social feed bolted onto the router. Every mandatory sub-requirement maps
onto that framing directly, and it stays on-topic for a routing application. That earlier note
also proposed feeding confirmed reports live into the route risk score; this PRD deliberately
does **not** do that. `route_scoring_service.py` and `corridor_matcher.py` are already built,
tested, and documented around one **immutable, versioned, historical** risk-data source
(`ROUTING_FEATURE_PRD.md` decisions 9-27). Wiring unmoderated live user reports into that
pipeline is a real, separate architectural change — a new risk-data source, an abuse-resistance
question (fake reports could steer routes), and a moderation-before-trust question — and belongs
in its own future PRD, not as a side effect of shipping the forum. This PRD's forum is a
self-contained feature that reuses this project's existing conventions (Alembic-owned schema,
FastAPI routers, cookie auth, Redis-backed abuse protection, typed frontend API clients) without
touching the routing vertical slice.

The replacement must also satisfy the same cross-cutting constraints already enforced elsewhere
in the codebase: only Nginx is client-facing, all state lives in PostgreSQL (not memory), the
project has one authoritative containerized test command, and secrets/limits come from validated
configuration with no committed usable defaults.

## Solution

An authenticated user (see `docs/CODEBASE_MAP.md` — login already gates the whole application)
can publish a hazard report ("post") with a title, body, hazard type, an approximate location,
and optional image/video attachments, with an explicit anonymity toggle that hides their identity
from every other user while the database still records true ownership for moderation, rate
limiting, and edit/delete authorization. Other users can comment on a post (also with optional
media and anonymity) and cast one upvote or downvote per post or comment, which the API tracks
as a single settable vote (up, down, or none) rather than independent increment calls. Every
user has a profile dashboard summarizing their own posts, comments, and net engagement received.

Authenticated users can also send each other direct messages carrying text and/or a single media
attachment. Recipients see new DMs and new votes on their own content as live in-app
notifications, delivered over a per-user Server-Sent Events stream backed by Redis Pub/Sub so
the browser never has to poll or manually refresh — a new capability for this codebase, whose
existing route-job status polling remains unchanged.

Media (images/videos) is capped in size and content type before it is written, stored on a
dedicated Docker volume outside PostgreSQL, and served back only through an authenticated
FastAPI route that checks the requester is allowed to see the owning post/comment/message
(respecting anonymity and DM privacy). This keeps PostgreSQL as the system of record for all
relational/state data (per the existing "persistence" constraint) without forcing large binary
blobs through the database, and mirrors how `osrm/data` already lives on its own ignored volume
rather than in Git or Postgres.

Every forum-writing endpoint (post, comment, vote, DM, media upload) sits behind the same kind of
Redis-backed rate limiting and capacity admission already implemented for routing
(`abuse_protection.py`, `auth_rate_limit.py`), fails closed the same way when Redis is
unavailable, and rejects oversized/invalid bodies before any database or disk write.

The application boots with cold-seeded demo data: a fixed set of clearly-marked seed accounts,
historical posts across hazard types, and comment/vote threads, created idempotently by the same
one-shot `initialize` service that already applies migrations and loads foundation data
(`docs/CODEBASE_MAP.md` — "Startup stages"), so the forum never launches empty in a demo or in
grading.

## User Stories

1. As an authenticated user, I want to publish a hazard report with a title, body, and hazard
   type, so that other drivers learn about a real road condition.
2. As a user, I want to attach images and/or a short video to my report, so that other drivers
   can see the hazard directly.
3. As a user, I want to attach an approximate location to my report, so that the report is
   useful to drivers near that spot.
4. As a user, I want an explicit toggle to post anonymously, so that I can report sensitive
   things (police, speed cameras) without my identity being shown to other users.
5. As a user, I want my true identity kept in the database even when I post anonymously, so that
   rate limiting, abuse defense, and my own ability to edit/delete the post still work.
6. As any user, I want anonymous posts and comments to never expose the author's email or user
   ID through any API response, so that anonymity is a real guarantee, not a UI-only label.
7. As a user, I want to comment on any post with text and optional media, so that I can confirm,
   refute, or add detail to a report.
8. As a user, I want to comment anonymously too, so that the same privacy option applies
   consistently to comments.
9. As a user, I want to upvote or downvote a post or comment, so that trustworthy reports rise
   and stale/false ones don't.
10. As a user, I want my vote on one target to be a single settable state (up, down, or none)
    rather than independent buttons, so that I can't inflate a score by clicking repeatedly.
11. As a user, I want to change or remove my vote, so that I can correct a mistaken click.
12. As a user, I want a profile dashboard showing my post count, comment count, and net votes
    received across everything I've posted, so that I can see my own reporting reputation.
13. As a user, I want the public feed to show current vote totals per post/comment without
    recomputing a sum over every vote row on each read, so that the feed stays responsive as
    the forum grows.
14. As a user, I want the feed ordered newest-first with paging, so that browsing many reports
    stays responsive.
15. As a user, I want to filter the feed by hazard type, so that I can find reports relevant to
    me quickly.
16. As a user, I want to send another user a direct message with text and/or one media
    attachment, so that I can ask a reporter for more detail privately.
17. As a user, I want to see only conversations I'm part of, so that other users' DMs stay
    private.
18. As a user, I want to see whether my sent message has been read, so that I know whether to
    expect a reply.
19. As a user, I want a live notification the moment I receive a new DM, so that I don't have to
    keep refreshing the page.
20. As a user, I want a live notification when someone upvotes or downvotes my post or comment,
    so that I know my content is getting engagement without refreshing.
21. As a user, I want to see a bounded unread-notification count and a paged notification list,
    so that I can catch up after being away.
22. As a user, I want to mark notifications as read, so that the unread indicator reflects only
    genuinely new activity.
23. As a user, I want the live notification connection to recover automatically after a brief
    network interruption, so that a dropped connection doesn't silently stop live updates.
24. As a user, I want image and video uploads rejected immediately when they exceed a configured
    size or use an unsupported type, so that I get clear feedback instead of a stalled upload.
25. As a user, I want uploaded media served back only to users allowed to see the owning
    post/comment/DM, so that private DM attachments and moderation state aren't publicly
    guessable by path.
26. As a legitimate user, I want a clear rate limit on posting, commenting, voting, and
    messaging, so that one abusive account can't flood the feed or my inbox.
27. As a legitimate user, I want a clear retry delay when I'm rate-limited, so that I know when
    I can try again.
28. As a user, I want invalid or oversized requests rejected before any database or disk write,
    so that abuse can't consume storage or Redis capacity.
29. As a user, I want to edit or delete my own post or comment, so that I can correct or retract
    a report.
30. As a user, I want another user's post/comment/DM ID to be inaccessible to me for
    editing/deleting, so that ownership is enforced everywhere, not only in the UI.
31. As a new visitor to the demo, I want the forum to already contain realistic historical
    reports, comments, and votes from seed accounts, so that the feed doesn't look empty before
    real users arrive.
32. As a grader, I want seed accounts clearly distinguishable from real accounts (e.g., a stable
    flag or naming convention), so that seed data can be excluded from certain checks without
    guessing.
33. As an operator, I want forum seeding to be idempotent, so that re-running initialization
    doesn't duplicate seed posts on every restart.
34. As an operator, I want forum media stored outside PostgreSQL on its own volume, so that large
    binary uploads don't bloat routine database backups and queries.
35. As an operator, I want Redis-backed forum rate limits and the SSE notification channel to
    fail closed/degrade in a controlled way when Redis is unavailable, so that a Redis outage
    produces bounded errors instead of unbounded queues or a crashed process.
36. As an operator, I want structured logs for forum writes and moderation actions that never
    include message/post body text, media bytes, or anonymous-author identity, so that logs stay
    privacy-safe like the rest of the system.
37. As a grader, I want every claimed forum feature covered by an actual documented test command,
    so that coverage claims can be verified the same way as the routing feature's.
38. As a grader, I want deterministic tests that don't depend on real image/video files or a
    live SSE client outside the test stack, so that forum tests run the same way on any clean
    machine.

## Implementation Decisions

1. **Scope boundary.** Ship the forum as a self-contained vertical slice that reuses existing
   authentication, configuration, rate-limiting, and initialization conventions. Do not modify
   `route_scoring_service.py`, `corridor_matcher.py`, or the versioned risk-data model. Any
   future live-hazard-feeds-routing integration is out of scope for this PRD.

2. **Module ownership.** New backend code lives under `backend/app/forum/` (posts, comments,
   votes, media), `backend/app/messaging/` (direct messages), and `backend/app/notifications/`
   (SSE stream, notification rows, Redis Pub/Sub publishing), mirroring the existing
   `backend/app/routing/` and `backend/app/geocoding/` module pattern. Each module keeps HTTP
   schemas, persistence, and pure logic (e.g., vote-state transitions) separately testable.

3. **Schema management.** All forum/messaging/notification tables are added through Alembic
   migrations under `backend/alembic/versions/`, never through FastAPI startup code, continuing
   the existing project rule.

4. **Core tables.** `forum_posts`, `forum_post_media`, `forum_comments`, `forum_comment_media`,
   `forum_votes` (one row per user per target, unique on `(user_id, target_type, target_id)`),
   `direct_messages`, `direct_message_media`, `notifications`. Posts and comments always store
   the true `author_user_id`; an `is_anonymous` flag controls only API-response visibility.

5. **Denormalized counters.** `forum_posts` and `forum_comments` store `upvote_count` and
   `downvote_count` columns updated atomically alongside each vote write inside one transaction,
   so feed reads never aggregate the `forum_votes` table. The dashboard aggregate (story 12) is
   computed from these counters, not a live vote scan.

6. **Vote model.** `PUT /api/forum/{post|comment}/{id}/vote` accepts `up`, `down`, or `none` and
   is idempotent: it upserts or deletes the caller's single `forum_votes` row for that target and
   adjusts the counters by the resulting delta in the same transaction. There is no separate
   increment-only endpoint.

7. **Anonymity enforcement.** Response serialization for posts/comments checks `is_anonymous` and
   omits `author_user_id`/email whenever true, replacing it with a fixed "Anonymous" label.
   Ownership checks (edit/delete/rate-limit key) always use the stored `author_user_id`
   server-side and never trust a client-supplied identity.

8. **Media storage.** Uploaded files are written to a dedicated Docker volume (implemented as the
   named Compose volume `forum_media`, mounted at `/data/forum-media` inside the `api` container
   only — not `worker`, since posting/commenting/voting/uploading are synchronous FastAPI work
   with no Celery task, per decision 24), never to PostgreSQL or Git. Each media row stores a
   generated storage key, declared content type, and byte size; the file is validated (size cap,
   allowed MIME types: a small fixed image and video allowlist) before being written to disk, and
   rejected before any write if it fails validation. The synchronous disk write runs via
   `asyncio.to_thread` so it never blocks the event loop.

9. **Media retrieval.** A single authenticated `GET /api/forum/media/{media_id}` endpoint streams
   the file only after checking the requester is allowed to see the owning post, comment, or DM
   (public post/comment media is readable by any authenticated user unless the post was removed;
   DM media is readable only by sender/recipient). Media is never served by a guessable static
   path.

10. **Size/type limits.** Maximum image size (default 5 MB), maximum video size (default 25 MB),
    and the accepted content-type allowlist are validated configuration (`config.py`), with
    sane-but-overridable defaults rather than a committed usable secret. A per-post and
    per-comment maximum media-item count (defaults 6 and 3) is also validated configuration —
    added during implementation, beyond what this PRD originally specified, because an unbounded
    attachment count on a single post is a way around the per-file size cap and "storage abuse"
    is an explicitly named course requirement (see PRD Problem Statement's guideline quote).

10a. **Request-size middleware exemption.** The project's existing `RequestSizeLimitMiddleware`
    (`request_bounds.py`) enforced one small blanket body-size ceiling (originally 16 KB, sized
    for JSON API bodies) across every route. Media uploads need a larger ceiling to reach this
    PRD's own tighter, content-type-specific checks at all. The middleware gained a path-suffix
    match (any path ending `/media`) that swaps in a larger configured ceiling — the larger of
    the image/video caps — only for upload endpoints; every other endpoint keeps the original
    small ceiling unchanged.

11. **Rate limiting.** Post creation, comment creation, vote changes, DM sends, and media uploads
    each get their own Redis-backed per-user (and per-IP for unauthenticated attempts, though the
    whole forum requires login) limit using the same `abuse_protection.py`/`auth_rate_limit.py`
    machinery already used for routing/geocoding/auth. Limits are checked before any disk or
    expensive database write. Exceeding a limit returns `429` with `Retry-After`.

12. **Fail-closed Redis dependency.** Forum writes (post/comment/vote/DM/media) fail closed with a
    controlled `503` when Redis-backed rate limiting is unavailable, matching the existing
    routing/auth behavior. Read-only feed/history endpoints remain available from PostgreSQL
    where safe. Proven (not just designed) by `backend/tests/test_forum_abuse_stack.py`: tight
    per-user limits on the shared `abuse-api` Compose test service show rapid repeated
    posting/commenting/voting/messaging returns `429`+`Retry-After`, and the existing
    `geocoding-unavailable-api` service (genuinely broken `REDIS_URL`, already reused by the
    route-job abuse tests) shows forum/DM writes return `503`+`Retry-After: 5` while feed/post/
    comment/conversation reads stay `200`.

13. **Notification rows.** A notification row is created for: a new DM to a recipient, a new
    upvote/downvote on a user's post/comment, and a new comment on a user's post. Each row stores
    `recipient_user_id`, a `kind`, a small JSON payload with the referenced IDs and (already
    anonymity-filtered) actor label, `created_at`, and nullable `read_at`.

14. **Live delivery.** Notification creation publishes a small event to a Redis Pub/Sub channel
    keyed per recipient (`forum-notifications:{user_id}`), from a dedicated `Redis.from_url(...)`
    connection rather than the app-wide cached `get_redis()` singleton. `GET
    /api/notifications/stream` is a Server-Sent Events endpoint that authenticates the caller,
    subscribes to that channel for the lifetime of the connection, and forwards events as SSE
    messages. SSE was chosen over WebSocket because delivery is one-directional (server to
    browser only); it avoids a bidirectional protocol upgrade this feature does not need and
    works over the existing HTTP/Nginx path without new infrastructure.

    **Load-bearing fix, not optional cleanup:** `RequestSizeLimitMiddleware` (added for the
    routing feature) drains and replays the ASGI `receive` channel for every request before
    delegating to the app. Wrapping this long-lived `StreamingResponse` endpoint in that pattern
    hung the *entire* server — every other concurrent request, on any connection — for as long as
    one notification stream stayed open, reproduced with the size-check logic stripped out down
    to the bare buffer-and-replay shape. Fixed by exempting `GET`/`HEAD` requests from that path
    entirely in `request_bounds.py` (also the semantically correct scope, since no endpoint here
    reads a body from a GET). Do not remove this exemption without re-verifying a live SSE
    connection against a concurrent request on a real Docker Compose stack — the bug is invisible
    in unit tests and in single-request manual checks.

15. **Reconnection.** The frontend SSE client uses the browser's native `EventSource`
    auto-reconnect behavior and, on every (re)connect, first fetches the bounded unread
    notification list over normal HTTP so a dropped connection cannot silently lose
    notifications generated while disconnected.

16. **Notification history.** `GET /api/notifications` returns a bounded, offset-paginated,
    newest-first list for the authenticated user, mirroring the existing route-history pagination
    convention, and also includes the caller's total `unread_count` in the same response so the
    frontend indicator never needs a second round trip. `POST /api/notifications/{id}/read` and
    `POST /api/notifications/read-all` update `read_at`, filtered by ownership; marking an
    already-read notification read again is a no-op 204, not a 404 — only a missing or
    not-owned notification is a 404.

17. **Direct messages.** `direct_messages` rows store `sender_user_id`, `recipient_user_id`,
    optional `body`, `created_at`, and nullable `read_at`. A conversation is derived from the pair
    of user IDs (no separate conversation/thread table in version 1). `GET
    /api/messages/{other_user_id}` returns the paged history between the caller and that user,
    filtered so a user can only ever query conversations they are part of.
    **Send transport:** `POST /api/messages/{recipient_user_id}` accepts one multipart request
    with `body` as a plain form field and an optional `file` upload, rather than the forum's
    create-then-attach-media two-call pattern (ticket 3). A DM carries at most one attachment
    (unlike a forum post's multiple images/videos), so one combined call is simpler for both the
    client and the server. This required `RequestSizeLimitMiddleware` to also match by path
    *prefix* (`/api/messages/`) in addition to its existing path-*suffix* (`/media`) match, since
    this endpoint has no dedicated `/media` sub-route to key off of.

18. **DM read receipts.** Opening a conversation (`GET /api/messages/{other_user_id}`) marks the
    caller's unread received messages in that conversation as read in the same request, and
    returns the updated rows so the sender's next poll/notification reflects it.

19. **Ownership and privacy.** Every forum/DM/notification lookup and mutation filters by
    authenticated owner or participant. Access to another user's private resource (DM
    conversation, notification, media requiring DM privacy) returns `404`, matching the existing
    route-history convention of not revealing existence.

20. **Cold seeding.** A dedicated seeding step (`backend/app/seed_forum_demo_data.py`), invoked
    from the one-shot `initialize` Compose service after migrations, foundation data, and the
    risk-data refresh (never from FastAPI startup), creates 6 clearly-marked seed accounts (a
    stable email pattern, `seed+<n>@example.local`, and the `users.is_seed_account` boolean added
    by the same migration that adds the forum tables), 9 historical posts spread across all 7
    hazard types, 11 comments, and 24 votes. The step is idempotent by construction rather than
    by a pre-check: post/comment primary keys are `uuid5(fixed_namespace, "seed-post-N")` (so a
    second run computes the *same* row identity and `ON CONFLICT DO NOTHING` is a true no-op),
    `users` upserts on its existing `email` unique constraint, `forum_votes` upserts on its
    existing `(user_id, target_type, target_id)` unique constraint, and every denormalized
    counter (`comment_count`, `upvote_count`, `downvote_count`) is *recomputed* from the actual
    seeded rows at the end of every run rather than incremented — so the step converges to the
    same state no matter how many times it runs, instead of merely avoiding duplicate rows.

21. **Seed data realism.** Seed posts and comments use plausible static text/hazard-type/location
    combinations authored ahead of time (no LLM call during initialization, keeping
    initialization deterministic and offline-safe); seed accounts never log in and are excluded
    from cold-seeded-vs-real distinctions the grader may want to check.

22. **Frontend structure.** New pages `frontend/src/pages/ForumPage.tsx` (feed, post
    creation/detail, comments, voting) and `frontend/src/pages/InboxPage.tsx` (DM conversation
    list and thread), new components under `frontend/src/components/forum/` and
    `frontend/src/components/messages/`, typed clients `frontend/src/api/forum.ts`,
    `frontend/src/api/messages.ts`, `frontend/src/api/notifications.ts`, and corresponding types
    under `frontend/src/types/`, following the existing typed-client-plus-tests pattern. Both
    pages are added to the existing `PageSwitcher`/`App.tsx` gated-by-login shell; no new
    authentication path is introduced.

23. **Notification indicator.** The session header (`App.tsx`'s `app-session-bar`) gains a
    live-updating unread-notification indicator (`NotificationIndicator`) fed by the SSE
    connection established once per signed-in session, alongside the existing sign-out control.
    Clicking it marks everything read (`POST /api/notifications/read-all`) and resets the badge
    immediately (optimistic; a future reconnect's refetch reconciles it if the request failed).
    Version 1 has no dropdown listing individual notifications — just the count — matching the
    ticket's "live-updating unread-notification indicator" scope without expanding it.

24. **Async boundary.** Forum/messaging/notification HTTP handlers use the existing asynchronous
    PostgreSQL/Redis access pattern (`db.py`, `redis_client.py`). No Celery task is required for
    posting/commenting/voting/DM-sending — these are ordinary bounded database writes, unlike
    routing's OSRM/PostGIS work, so introducing a job queue here would add complexity without a
    matching latency problem.

25. **Health/readiness.** Forum functionality does not add new required-dependency readiness
    checks beyond the existing PostgreSQL/Redis checks, since it introduces no new external
    service.

26. **Error contract.** Invalid input returns `422`. Missing/expired session returns `401`.
    Ownership/privacy violations return `404`. Rate limits return `429` with `Retry-After`.
    Redis unavailability for a write path returns `503`. Oversized/invalid media returns `413`
    or `422` before any disk write.

## Testing Decisions

1. **Primary testing seam.** The public HTTP forum/messaging/notification workflow: authenticate,
   post, comment, vote, upload/fetch media, send/read a DM, receive a live notification, list
   history, edit/delete own content, and hit rate limits — matching the routing feature's
   integration-first approach.

2. **Unit coverage.** Vote-state transition logic (up/down/none upsert and counter delta),
   anonymity-filtered serialization, media size/type validation, rate-limit configuration
   validation, and notification-event payload construction, tested without HTTP or a database
   where the logic is pure.

3. **Integration coverage.** Real disposable PostgreSQL and Redis. Cover post/comment/vote CRUD
   and ownership, anonymous-author leak prevention across every response shape, counter
   correctness under concurrent votes, media upload/validation/retrieval and privacy filtering,
   DM conversation isolation between users, notification row creation for each triggering event,
   Redis Pub/Sub publish-on-write, rate-limit enforcement and fail-closed behavior, and cold-seed
   idempotency (running the seed step twice produces no duplicates).

4. **SSE testing.** Test the notification stream by asserting published Redis Pub/Sub messages
   and the endpoint's authenticated subscribe/forward behavior in the test stack, without
   depending on a real browser `EventSource`; cover the reconnect-then-fetch-unread-list
   frontend behavior in a frontend test with a mocked `EventSource`.

5. **Frontend coverage.** Extend the existing React Testing Library/Vitest approach: feed
   rendering/paging/filtering, post/comment/media form validation, vote toggling, DM thread
   rendering and read-state, notification indicator updates from mocked SSE events, and
   login-gating consistent with other pages.

6. **Security coverage.** Verify anonymous authorship never appears in any API response; DM
   access, edit, and delete are ownership-filtered and return `404` for non-owners; media
   endpoints reject path/ID guessing outside authorized scope; rate limits hold under rapid
   repeated requests; and no forum/DM/notification log line contains body text or media bytes.

7. **Stress coverage.** Extend the existing Locust stress profile with rapid post/comment/vote/DM
   bursts from many simulated users and one abusive user, verifying bounded `429`/`503`
   responses, no process crash, and no cross-user data leakage, consistent with the routing
   feature's stress acceptance criteria.

8. **Fake media in tests.** Automated tests use small fixed in-memory byte payloads for
   image/video content, never real media files, so the suite stays fast and has no external
   asset dependency.

9. **Execution model.** Forum tests run inside the same authoritative containerized test command
   (`scripts/run_grading_validation.sh` and the `compose.test.yaml` stack) as the rest of the
   suite, using committed fixtures, not a separate test entry point.

10. **Feature-to-test matrix.** Documentation maps every implemented forum/DM/notification feature
    to actual test files and commands, following the same rule as the routing feature: never list
    a test that doesn't exist or claim coverage a test doesn't execute.

## Out of Scope

- Feeding hazard reports into `route_scoring_service.py`/`corridor_matcher.py` or otherwise
  influencing route ranking (see Problem Statement — deliberately deferred to a future PRD).
- Comment threading/nesting beyond a single flat comment list per post.
- Message "conversation" as a first-class entity with its own ID; a DM thread is always derived
  from the sender/recipient pair.
- Group DMs; direct messaging is strictly one-to-one.
- Push notifications outside the browser tab (native mobile/desktop push, email digests).
- Content moderation tooling (admin review queue, automated content filtering) beyond
  owner-initiated edit/delete and community voting.
- Full-text search across posts/comments.
- Editing/removing another user's vote, comment, or post as a moderator role.
- Media transcoding, thumbnailing, or streaming-optimized video delivery; uploaded files are
  served as-is under the configured size caps.
- WebSocket transport (see Implementation Decision 14 for the SSE rationale).
- Using an LLM for seed-content generation or live moderation (may be revisited under the
  project's separate LLM-integration feature, not this PRD).
- Any change to authentication, route jobs, corridor matching, or risk-data versioning.
