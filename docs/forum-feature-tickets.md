# Forum feature tickets

These tickets implement `docs/FORUM_FEATURE_PRD.md`. They assume the foundation already built
for routing (Alembic, one-shot `initialize`, cookie auth, Redis-backed abuse protection,
`docs/CODEBASE_MAP.md`'s module/testing conventions) and do not modify it.

## 1. Add forum/messaging/notification schema

**What to build:** One Alembic migration that creates every table this feature needs, so later
tickets never touch schema again.

**Blocked by:** None — can start immediately.

**Status:** done (migration `0006_forum_foundation.py`)

- [x] `forum_posts`, `forum_post_media`, `forum_comments`, `forum_comment_media`, `forum_votes`,
      `direct_messages`, `direct_message_media`, and `notifications` tables exist with the
      columns described in PRD decision 4.
- [x] `forum_votes` has a unique constraint on `(user_id, target_type, target_id)`.
- [x] `forum_posts`/`forum_comments` include `upvote_count`/`downvote_count` integer columns
      defaulting to zero.
- [x] `users` gains an `is_seed_account` boolean column defaulting to false.
- [x] Foreign keys enforce that posts/comments/votes/messages/notifications reference a real
      user, and media rows reference a real owning post/comment/message.
- [x] Indexes support the required access patterns: feed paging by `created_at`, a user's own
      posts/comments, a DM conversation by the sender/recipient pair, and a user's notifications
      by `created_at`.
- [x] The migration applies cleanly against a real PostGIS database (verified via Docker Compose,
      not just reviewed) as part of the same migration run that already applies tickets 0001-0005.
      No dedicated foundation-test fixture exercises it yet — direct-messages/notifications
      tables stay unused until tickets 4-5 land, so there is nothing to assert against today.

## 2. Deliver the core hazard-report feed (posts, comments, votes)

**What to build:** Authenticated users can create, read, edit, and delete hazard-report posts
and comments (text only in this ticket), with anonymity and voting, before media or DMs exist.

**Blocked by:** 1. Add forum/messaging/notification schema.

**Status:** done (`backend/app/forum/routes.py`)

- [x] `POST /api/forum/posts` creates a post with title, body, hazard type, optional location,
      and `is_anonymous`; the stored `author_user_id` is always the real caller.
- [x] `GET /api/forum/posts` returns a newest-first, offset-paginated feed, optionally filtered
      by hazard type, with anonymity-filtered author fields and current vote counters.
- [x] `GET /api/forum/posts/{id}` returns full post detail. Comments are fetched separately
      through `GET /api/forum/posts/{id}/comments` (its own offset pagination) rather than
      embedded, so opening a long comment thread never forces one oversized response — this
      revises the ticket's original "detail plus its comments" wording to match what was built.
- [x] `PATCH /api/forum/posts/{id}` and `DELETE /api/forum/posts/{id}` are restricted to the
      real author; another user's request returns 404.
- [x] `POST /api/forum/posts/{id}/comments`, and matching `PATCH`/`DELETE` for a comment, follow
      the same anonymity and ownership rules as posts.
- [x] `PUT /api/forum/posts/{id}/vote` and `PUT /api/forum/comments/{id}/vote` accept
      `up`/`down`/`none`, upsert the caller's single `forum_votes` row, and adjust
      `upvote_count`/`downvote_count` atomically in the same transaction (guarded by a
      `pg_advisory_xact_lock` so two concurrent votes from the same user can never both read "no
      existing vote" and double-apply a counter delta).
- [x] `GET /api/forum/me/dashboard` returns the caller's post count, comment count, and net votes
      received, computed from the denormalized counters.
- [x] Every author field in every response respects `is_anonymous`; `test_forum_stack.py`'s
      `test_anonymous_post_and_comment_hide_author_from_others_but_not_from_self` asserts no
      response body contains the real author's ID or email for an anonymous post/comment.
- [x] Unit tests (`test_forum_routes.py`) cover the vote-label mapping and anonymity-filtered
      serialization in isolation; integration tests (`test_forum_stack.py`, 9 tests) cover CRUD,
      ownership, anonymity, and counter correctness against real PostgreSQL — verified via a live
      Docker Compose run, not just written and assumed to pass.

## 3. Add forum/comment media upload and retrieval

**What to build:** Let posts and comments carry image/video attachments, stored outside
PostgreSQL, validated and served safely.

**Blocked by:** 2. Deliver the core hazard-report feed.

**Status:** done (`backend/app/forum/media_storage.py`, media endpoints in
`backend/app/forum/routes.py`)

- [x] A Compose-managed named volume (`forum_media`) is mounted into the `api` container at the
      configurable `FORUM_MEDIA_STORAGE_PATH` (default `/data/forum-media`); not committed to
      Git. The `worker` container does not need it — posting/commenting/voting/uploading are
      synchronous FastAPI/PostgreSQL work with no Celery task, per PRD decision 24, so there is
      no worker-side code path that touches this volume. In the test stack, `compose.test.yaml`
      resets `api`'s volumes entirely (`!reset []`); the path still works there because
      `write_media_file` creates the directory on first use inside the container's own ephemeral
      filesystem, so no test-specific volume wiring was needed.
- [x] Maximum image size (default 5 MB), maximum video size (default 25 MB), and an accepted
      content-type allowlist (`image/jpeg,image/png,image/webp` /
      `video/mp4,video/webm`) are validated configuration with no committed usable default beyond
      those sane defaults. A per-post/per-comment media-count cap (default 6 / 3) was added
      beyond the original ticket scope, since "storage abuse" is an explicitly named course
      requirement and an unbounded attachment count on one post is an easy way around the
      per-file size cap.
- [x] `POST /api/forum/posts/{id}/media` and `POST /api/forum/comments/{id}/media` reject
      oversized or disallowed uploads with `413`/`422` before any disk write. Uploads are also
      restricted to the post's/comment's own author (same ownership rule as edit/delete), which
      the ticket didn't explicitly require but which follows directly from "you can only change
      what you own."
- [x] Accepted uploads are written to the volume under a generated (`uuid4().hex`, non-guessable)
      storage key via `asyncio.to_thread` so the synchronous disk write never blocks the event
      loop; a `forum_post_media`/`forum_comment_media` row records the key, content type, and
      size.
- [x] `GET /api/forum/media/{media_id}` streams the file only if the requester may see the
      owning post/comment (a single query covering both tables, filtered on `status = 'active'`
      up the post/comment chain); unauthorized or post-deleted access returns 404. Requires
      authentication like the rest of the forum, but does not additionally restrict by
      anonymity — anonymity conceals authorship, not content, matching PRD decision 9.
- [x] Media upload has its own Redis-backed per-user/per-IP rate limit
      (`forum_media_upload_user_rate_limit`/`..._ip_rate_limit`) rather than waiting for ticket 6,
      since shipping an unlimited-upload endpoint even temporarily would be a real abuse gap.
- [x] `RequestSizeLimitMiddleware` (`backend/app/request_bounds.py`) gained a path-suffix-based
      exemption (`media_max_body_bytes`, matched on paths ending `/media`) so upload requests
      aren't rejected at the old blanket 16 KB JSON-body ceiling before reaching this ticket's
      own tighter, content-type-specific checks.
- [x] Integration tests (`test_forum_media_stack.py`, 9 tests) cover accepted/rejected size and
      type combinations, ownership, the per-post media cap, retrieval after post deletion, and
      missing-media 404s, using small fixed in-memory byte payloads rather than real media files
      — verified via a live Docker Compose run (real PostGIS, real Redis, real disk volume), not
      just written and assumed to pass. Unit tests (`test_forum_media.py`, 12 tests) cover the
      pure size/type classification logic and the storage write/read round trip in isolation.

## 4. Deliver direct messaging

**What to build:** One-to-one authenticated messaging with optional media, isolated per
conversation pair.

**Blocked by:** 1. Add forum/messaging/notification schema; 3. Add forum/comment media upload
and retrieval (reuses its storage/validation path for message attachments).

**Status:** done (`backend/app/messaging/routes.py`, `frontend/src/pages/InboxPage.tsx`)

- [x] `POST /api/messages/{recipient_user_id}` creates a message with optional body and/or one
      media attachment reusing ticket 3's storage and validation, as a single multipart request
      (`body` as a form field, `file` as an optional upload) rather than a create-then-attach
      pair — DMs carry at most one attachment, unlike posts, so one combined call was simpler
      than the forum's two-step flow. This required extending `RequestSizeLimitMiddleware` with
      a path-*prefix* match (`/api/messages/`) alongside its existing path-*suffix* match
      (`/media`), since this endpoint accepts an attachment without a dedicated `/media` route.
- [x] `GET /api/forum/media/{media_id}` (the same shared endpoint from ticket 3, per PRD decision
      9) now also serves `direct_message_media`, visible only to the message's sender or
      recipient — no separate DM-specific media endpoint was added.
- [x] `GET /api/messages/{other_user_id}` returns the paged conversation between the caller and
      that user, newest-last (chat order: fetched newest-first via `OFFSET`/`LIMIT` then
      reversed, matching this codebase's existing offset-pagination convention rather than a
      cursor-based "before" scheme), and is only reachable by the two participants because the
      query is always scoped to `(sender, recipient) = (me, other) OR (other, me)`.
- [x] Opening a conversation marks the caller's unread received messages in it as read in the
      same request (one `UPDATE` immediately before the `SELECT`, same transaction).
- [x] `GET /api/messages` lists the caller's conversations (other participant, last message
      preview, unread count), newest-activity-first, via one query using `ROW_NUMBER() OVER
      (PARTITION BY other_user_id ...)` to pick each partner's latest message.
- [x] A user cannot query, and gets 404 for, a conversation they are not part of. There is no
      separate conversation ID to guess in the first place — a conversation is always derived
      from `(caller, other_user_id)`, so this is true by construction rather than an extra check.
- [x] Integration tests (`test_messages_stack.py`, 10 tests) cover sending, pagination order,
      read-state transitions, media attachment (including that a non-participant gets 404 on the
      attachment), and cross-user isolation — verified via a live Docker Compose run. Unit tests
      (`test_messages_routes.py`, 4 tests) cover the pure response-serialization helpers.
      Discovered and fixed along the way: two tests need three fresh signups in one test, but the
      shared `api` test service caps `SIGNUP_RATE_LIMIT` at 2 per IP per window — the test
      helper now clears that limiter before every individual signup, not just once per test.

## 5. Deliver live notifications over Server-Sent Events

**What to build:** Real-time in-app notification delivery for new DMs and new votes, without
polling, per PRD decisions 13-16.

**Blocked by:** 2. Deliver the core hazard-report feed; 4. Deliver direct messaging.

**Status:** done (`backend/app/notifications/`, `frontend/src/components/notifications/NotificationIndicator.tsx`)

- [x] A notification row is created for: a new DM to a recipient, a new upvote/downvote on a
      user's post/comment, and a new comment on a user's post; creation is anonymity-filtered
      before storage of the actor label (`create_notification` also unconditionally skips
      self-notifications — voting on or commenting on your own content never notifies you).
      Clearing a vote back to `none` does not notify (only a genuine new up/down vote does).
- [x] Notification creation publishes a small event to a per-recipient Redis Pub/Sub channel,
      but *after* the transaction that wrote the row commits (the route handler calls
      `publish_notification` once its `async with get_engine().begin()` block has exited), so a
      subscriber that reacts by calling `GET /api/notifications` can never race ahead of the row
      it's reacting to.
- [x] `GET /api/notifications/stream` authenticates the caller, subscribes to their channel, and
      forwards events as Server-Sent Events for the connection's lifetime.
- [x] `GET /api/notifications` returns a bounded, offset-paginated, newest-first list (including
      `unread_count` in the same response, so the frontend doesn't need a second call); `POST
      /api/notifications/{id}/read` and `POST /api/notifications/read-all` update `read_at`,
      filtered by ownership.
- [x] The frontend SSE client (`NotificationIndicator`) re-fetches the unread count on every
      `EventSource.onopen` firing — which the browser triggers on the initial connect *and* on
      every automatic reconnect — so a dropped connection cannot silently lose notifications
      generated while disconnected.
- [x] Integration tests (`test_notifications_stack.py`, 8 tests) assert notification creation,
      anonymity filtering, self-vote/clear-vote suppression, read-state transitions, and
      ownership scoping; one test opens a real SSE connection with `httpx.Client.stream(...)`
      and asserts a live event arrives after another client triggers it — verified via a live
      Docker Compose run, not a mocked transport. Frontend tests
      (`NotificationIndicator.test.tsx`, 5 tests) cover the fetch-on-open, increment-on-message,
      refetch-on-reconnect, mark-all-read, and unmount-closes-connection behavior with a mocked
      `EventSource` class (jsdom has no native `EventSource`).
- [x] **Critical bug found and fixed during verification, not just written and assumed correct:**
      the project's existing `RequestSizeLimitMiddleware` (added for the routing feature, reused
      here) drains and replays the ASGI `receive` channel for every request. Wrapping a
      long-lived `StreamingResponse` (this SSE endpoint) in that pattern hung the *entire* server
      — every other concurrent request on any connection, including `/health/live` — for as long
      as one notification stream stayed open. Root-caused empirically through a sequence of
      isolated repros (bare `redis.asyncio` pubsub alongside a heartbeat: fine; bare FastAPI
      `StreamingResponse` under real uvicorn: fine; the same bare app with only the minimal
      receive-buffer-and-replay middleware pattern added, no size-check logic at all: reproduces
      the hang). Fixed by exempting `GET`/`HEAD` requests from the buffer-and-replay path
      entirely in `request_bounds.py` — semantically correct anyway, since no endpoint in this
      API reads a body from a GET. This also means the media-upload prefix/suffix exemptions
      added in tickets 3-4 apply only to non-GET requests now, which was already the only case
      that mattered (uploads are POSTs).

## 6. Add forum/messaging rate limiting and abuse protection

**What to build:** Extend the existing Redis-backed abuse-protection machinery to every forum
write path.

**Blocked by:** 2. Deliver the core hazard-report feed; 3. Add forum/comment media upload and
retrieval; 4. Deliver direct messaging.

**Status:** ready-for-agent (media upload's limit already landed early, see below)

- [x] Media uploads already have their own Redis-backed per-user/per-IP limit
      (`forum-media-upload` action, ticket 3) — shipped ahead of this ticket rather than leaving
      the endpoint unlimited in the meantime.
- [x] Post creation, comment creation, and vote changes already have their own Redis-backed
      per-user/per-IP limits (ticket 2, actions `forum-post-create`/`forum-comment-create`/
      `forum-vote`).
- [x] DM sends already have their own Redis-backed per-user/per-IP limit (`dm-send` action,
      ticket 4) — shipped alongside that ticket rather than leaving it unlimited in the meantime.
- [x] `enforce_action_rate_limit` (shared by every action above) already sets `Retry-After` on
      every `429`.
- [ ] Redis unavailability makes forum/DM writes fail closed with a controlled `503`; read-only
      feed/history endpoints remain available from PostgreSQL where safe.
- [ ] Numeric limits are validated configuration, not constants scattered through endpoints.
- [ ] Integration/abuse tests prove rapid repeated posting/commenting/voting/messaging from one
      user is bounded, and that a Redis outage produces the documented fail-closed behavior
      rather than an unbounded queue or crash.

## 7. Cold-seed forum demo data

**What to build:** Make the forum launch with realistic historical content, per PRD decisions
20-21.

**Blocked by:** 1. Add forum/messaging/notification schema; 2. Deliver the core hazard-report
feed.

**Status:** ready-for-agent

- [ ] A seeding step creates a fixed set of `is_seed_account=true` users with a stable email
      pattern, a fixed set of historical posts spread across hazard types, comment threads, and
      votes.
- [ ] The step runs from the one-shot `initialize` Compose service after migrations and
      foundation data, never from FastAPI startup.
- [ ] The step is idempotent: running `initialize` twice produces no duplicate seed rows,
      verified by a test that runs it twice and asserts stable row counts.
- [ ] Seed content is fixed static text/data authored ahead of time; no network or LLM call
      happens during seeding.

## 8. Build the forum and messaging frontend

**What to build:** Give users a working UI for everything tickets 2-7 deliver.

**Blocked by:** 2. Deliver the core hazard-report feed; 3. Add forum/comment media upload and
retrieval; 4. Deliver direct messaging; 5. Deliver live notifications over Server-Sent Events.

**Status:** ready-for-agent

- [ ] `ForumPage.tsx` renders the paged, filterable feed, a post-creation form (title, body,
      hazard type, location, anonymity toggle, media picker), post detail with comments, and
      voting controls.
- [ ] `InboxPage.tsx` renders the conversation list and an open thread with message composition,
      media attachment, and read-state display.
- [ ] Both pages are added to the existing `PageSwitcher`/`App.tsx` gated-by-login shell.
- [ ] The session header shows a live-updating unread-notification indicator fed by the SSE
      connection established once per signed-in session.
- [ ] Typed API clients (`api/forum.ts`, `api/messages.ts`, `api/notifications.ts`) and matching
      types under `types/` follow the existing client-plus-tests pattern.
- [ ] Frontend tests cover feed rendering/paging/filtering, form validation, vote toggling, DM
      thread rendering, and notification indicator updates, following the existing React Testing
      Library/Vitest conventions.

## 9. Extend security and stress validation to the forum

**What to build:** Prove the whole feature meets the same security/abuse bar as routing, per PRD
Testing Decisions 6-7.

**Blocked by:** 6. Add forum/messaging rate limiting and abuse protection; 8. Build the forum and
messaging frontend.

**Status:** ready-for-agent

- [ ] Security tests verify anonymous authorship never appears in any response, DM/edit/delete
      access is ownership-filtered and returns 404 for non-owners, media endpoints resist
      path/ID guessing, and no forum/DM/notification log line contains body text or media bytes.
- [ ] The existing Locust stress profile is extended with rapid post/comment/vote/DM bursts from
      many simulated users and one abusive user, asserting bounded `429`/`503` responses, no
      process crash, and no cross-user data leakage.
- [ ] `docs/DOCUMENTATION_GUIDE.md` and `docs/CODEBASE_MAP.md` are updated to list the new forum
      modules, tables, and tests, following those documents' own maintenance rules.
- [ ] The feature-to-test matrix (see `ROUTING_FEATURE_PRD.md` Testing Decision 18's equivalent)
      is extended to cover every forum feature claimed complete.
