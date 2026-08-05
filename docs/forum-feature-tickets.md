# Forum feature tickets

These tickets implement `docs/FORUM_FEATURE_PRD.md`. They assume the foundation already built
for routing (Alembic, one-shot `initialize`, cookie auth, Redis-backed abuse protection,
`docs/CODEBASE_MAP.md`'s module/testing conventions) and do not modify it.

## 1. Add forum/messaging/notification schema

**What to build:** One Alembic migration that creates every table this feature needs, so later
tickets never touch schema again.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `forum_posts`, `forum_post_media`, `forum_comments`, `forum_comment_media`, `forum_votes`,
      `direct_messages`, `direct_message_media`, and `notifications` tables exist with the
      columns described in PRD decision 4.
- [ ] `forum_votes` has a unique constraint on `(user_id, target_type, target_id)`.
- [ ] `forum_posts`/`forum_comments` include `upvote_count`/`downvote_count` integer columns
      defaulting to zero.
- [ ] `users` gains an `is_seed_account` boolean column defaulting to false.
- [ ] Foreign keys enforce that posts/comments/votes/messages/notifications reference a real
      user, and media rows reference a real owning post/comment/message.
- [ ] Indexes support the required access patterns: feed paging by `created_at`, a user's own
      posts/comments, a DM conversation by the sender/recipient pair, and a user's notifications
      by `created_at`.
- [ ] The migration is idempotent-safe to apply on a clean database and is exercised by the
      existing foundation/migration test path.

## 2. Deliver the core hazard-report feed (posts, comments, votes)

**What to build:** Authenticated users can create, read, edit, and delete hazard-report posts
and comments (text only in this ticket), with anonymity and voting, before media or DMs exist.

**Blocked by:** 1. Add forum/messaging/notification schema.

**Status:** ready-for-agent

- [ ] `POST /api/forum/posts` creates a post with title, body, hazard type, optional location,
      and `is_anonymous`; the stored `author_user_id` is always the real caller.
- [ ] `GET /api/forum/posts` returns a newest-first, offset-paginated feed, optionally filtered
      by hazard type, with anonymity-filtered author fields and current vote counters.
- [ ] `GET /api/forum/posts/{id}` returns full post detail plus its comments.
- [ ] `PATCH /api/forum/posts/{id}` and `DELETE /api/forum/posts/{id}` are restricted to the
      real author; another user's request returns 404.
- [ ] `POST /api/forum/posts/{id}/comments`, and matching `PATCH`/`DELETE` for a comment, follow
      the same anonymity and ownership rules as posts.
- [ ] `PUT /api/forum/posts/{id}/vote` and `PUT /api/forum/comments/{id}/vote` accept
      `up`/`down`/`none`, upsert the caller's single `forum_votes` row, and adjust
      `upvote_count`/`downvote_count` atomically in the same transaction.
- [ ] `GET /api/forum/me/dashboard` returns the caller's post count, comment count, and net votes
      received, computed from the denormalized counters.
- [ ] Every author field in every response respects `is_anonymous`; an integration test asserts
      no response body contains the real author's ID or email for an anonymous post/comment.
- [ ] Unit tests cover the vote upsert/delta logic in isolation; integration tests cover CRUD,
      ownership, anonymity, and counter correctness against real PostgreSQL.

## 3. Add forum/comment media upload and retrieval

**What to build:** Let posts and comments carry image/video attachments, stored outside
PostgreSQL, validated and served safely.

**Blocked by:** 2. Deliver the core hazard-report feed.

**Status:** ready-for-agent

- [ ] A Compose-managed volume is mounted into the `api` (and `worker`, if later needed)
      container for forum media; the path is configurable and not committed to Git.
- [ ] Maximum image size, maximum video size, and an accepted content-type allowlist are
      validated configuration with no committed usable default.
- [ ] `POST /api/forum/posts/{id}/media` and the comment equivalent reject oversized or
      disallowed uploads with a `413`/`422` before any disk write.
- [ ] Accepted uploads are written to the volume under a generated (non-guessable) storage key,
      and a `forum_post_media`/`forum_comment_media` row records the key, content type, and size.
- [ ] `GET /api/forum/media/{media_id}` streams the file only if the requester may see the
      owning post/comment (respecting removed/anonymous state); unauthorized access returns 404.
- [ ] Media upload is covered by the same rate limiting as post/comment creation (ticket 6) once
      that ticket lands; until then, a per-user upload limit is still enforced.
- [ ] Integration tests cover accepted/rejected size and type combinations, storage-key
      non-guessability, and access-control filtering, using small fixed in-memory byte payloads
      rather than real media files.

## 4. Deliver direct messaging

**What to build:** One-to-one authenticated messaging with optional media, isolated per
conversation pair.

**Blocked by:** 1. Add forum/messaging/notification schema; 3. Add forum/comment media upload
and retrieval (reuses its storage/validation path for message attachments).

**Status:** ready-for-agent

- [ ] `POST /api/messages/{recipient_user_id}` creates a message with optional body and/or one
      media attachment reusing ticket 3's storage and validation.
- [ ] `GET /api/messages/{other_user_id}` returns the paged conversation between the caller and
      that user, newest-last (chat order), and is only reachable by the two participants.
- [ ] Opening a conversation marks the caller's unread received messages in it as read in the
      same request.
- [ ] `GET /api/messages` lists the caller's conversations (other participant, last message
      preview, unread count), newest-activity-first.
- [ ] A user cannot query, and gets 404 for, a conversation they are not part of.
- [ ] Integration tests cover sending, pagination, read-state transitions, media attachment, and
      cross-user isolation.

## 5. Deliver live notifications over Server-Sent Events

**What to build:** Real-time in-app notification delivery for new DMs and new votes, without
polling, per PRD decisions 13-16.

**Blocked by:** 2. Deliver the core hazard-report feed; 4. Deliver direct messaging.

**Status:** ready-for-agent

- [ ] A notification row is created for: a new DM to a recipient, a new upvote/downvote on a
      user's post/comment, and a new comment on a user's post; creation is anonymity-filtered
      before storage of the actor label.
- [ ] Notification creation publishes a small event to a per-recipient Redis Pub/Sub channel in
      the same request that writes the triggering row.
- [ ] `GET /api/notifications/stream` authenticates the caller, subscribes to their channel, and
      forwards events as Server-Sent Events for the connection's lifetime.
- [ ] `GET /api/notifications` returns a bounded, offset-paginated, newest-first list; `POST
      /api/notifications/{id}/read` and a bulk mark-all-read endpoint update `read_at`, filtered
      by ownership.
- [ ] The frontend SSE client re-fetches the unread list on every (re)connect so a dropped
      connection cannot silently lose notifications generated while disconnected.
- [ ] Integration tests assert Pub/Sub publish-on-write and authenticated subscribe/forward
      behavior without requiring a real browser `EventSource`.
- [ ] Frontend tests cover the reconnect-then-fetch-unread-list behavior with a mocked
      `EventSource`.

## 6. Add forum/messaging rate limiting and abuse protection

**What to build:** Extend the existing Redis-backed abuse-protection machinery to every forum
write path.

**Blocked by:** 2. Deliver the core hazard-report feed; 3. Add forum/comment media upload and
retrieval; 4. Deliver direct messaging.

**Status:** ready-for-agent

- [ ] Post creation, comment creation, vote changes, DM sends, and media uploads each have their
      own Redis-backed per-user limit, checked before any database or disk write.
- [ ] Exceeding a limit returns `429` with `Retry-After`.
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
