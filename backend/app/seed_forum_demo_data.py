from __future__ import annotations

import json
import os
import struct
import zlib
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import psycopg
from psycopg.rows import dict_row

from app.auth import hash_password
from app.config import get_settings
from app.forum.media_storage import write_media_file
from app.initialize_foundation import synchronous_database_url

_SEED_NAMESPACE = uuid5(NAMESPACE_URL, "https://sa-bracha.example/forum-seed")
_SEED_PASSWORD_HASH = hash_password("seed-accounts-never-log-in")
_NOW = datetime.now(timezone.utc)


def _seed_uuid(key: str) -> UUID:
    return uuid5(_SEED_NAMESPACE, key)


def _solid_color_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A minimal, dependency-free solid-color PNG, used as a stand-in demo photo — the
    seed script otherwise has no source of real hazard photography to attach."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = bytes([0]) + bytes(rgb) * width
    idat = zlib.compress(row * height, 9)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _days_ago(days: float) -> datetime:
    return _NOW - timedelta(days=days)


# Six recurring "regulars" with varied profiles, matching real signup constraints.
SEED_USERS: list[dict[str, object]] = [
    {"key": "seed-user-1", "email": "seed+1@example.local", "driving_experience": "experienced", "vehicle_type": "car", "avoid_tolls": False, "avoid_highways": False},
    {"key": "seed-user-2", "email": "seed+2@example.local", "driving_experience": "novice", "vehicle_type": "car", "avoid_tolls": True, "avoid_highways": False},
    {"key": "seed-user-3", "email": "seed+3@example.local", "driving_experience": "experienced", "vehicle_type": "motorcycle", "avoid_tolls": False, "avoid_highways": True},
    {"key": "seed-user-4", "email": "seed+4@example.local", "driving_experience": "experienced", "vehicle_type": "truck", "avoid_tolls": True, "avoid_highways": True},
    {"key": "seed-user-5", "email": "seed+5@example.local", "driving_experience": "novice", "vehicle_type": "car", "avoid_tolls": False, "avoid_highways": False},
    {"key": "seed-user-6", "email": "seed+6@example.local", "driving_experience": "experienced", "vehicle_type": "car", "avoid_tolls": False, "avoid_highways": False},
]

# Nine historical reports spread across hazard types and general (non-exact) locations.
SEED_POSTS: list[dict[str, object]] = [
    {
        "key": "seed-post-pothole-1", "author_key": "seed-user-1", "hazard_type": "pothole",
        "is_anonymous": False, "days_ago": 9,
        "title": "Deep pothole on the Ayalon northbound shoulder",
        "body": "Right after the interchange there's a pothole wide enough to catch a wheel. "
                "Cars are swerving into the lane to avoid it, so watch your mirrors.",
        "longitude": 34.7925, "latitude": 32.0729,
    },
    {
        "key": "seed-post-pothole-2", "author_key": "seed-user-4", "hazard_type": "pothole",
        "is_anonymous": False, "days_ago": 2,
        "title": "Cluster of potholes near the Route 4 junction, Herzliya",
        "body": "Several potholes in the right lane approaching the junction. Rough enough that "
                "trucks are moving into the left lane well in advance.",
        "longitude": 34.8437, "latitude": 32.1624,
    },
    {
        "key": "seed-post-flooding-1", "author_key": "seed-user-2", "hazard_type": "flooding",
        "is_anonymous": True, "days_ago": 5,
        "title": "Underpass flooding again on Begin Road",
        "body": "Standing water covering most of the lane after this afternoon's rain. "
                "It cleared last time within a few hours, but go slow until it does.",
        "longitude": 34.7818, "latitude": 31.7683,
    },
    {
        "key": "seed-post-broken-signal-1", "author_key": "seed-user-3", "hazard_type": "broken_signal",
        "is_anonymous": False, "days_ago": 7,
        "title": "Traffic light stuck on flashing yellow, Dizengoff junction",
        "body": "The signal has been flashing yellow in every direction since this morning. "
                "Treat it as a four-way stop and expect some confused drivers.",
        "longitude": 34.7744, "latitude": 32.0819,
    },
    {
        "key": "seed-post-poor-lighting-1", "author_key": "seed-user-5", "hazard_type": "poor_lighting",
        "is_anonymous": False, "days_ago": 12,
        "title": "Several streetlights out on the Route 6 service road",
        "body": "A long stretch is completely dark after sunset. Pedestrians crossing near the "
                "bus stop are hard to see until you're close, so slow down at night.",
        "longitude": 34.9482, "latitude": 32.1892,
    },
    {
        "key": "seed-post-speed-bump-1", "author_key": "seed-user-6", "hazard_type": "illegal_speed_bump",
        "is_anonymous": True, "days_ago": 15,
        "title": "Unmarked speed bump added near a Haifa Bay side street",
        "body": "Someone installed a makeshift speed bump with no paint or signage. It's easy to "
                "hit it at normal speed if you don't already know it's there.",
        "longitude": 35.0499, "latitude": 32.7940,
    },
    {
        "key": "seed-post-crash-1", "author_key": "seed-user-1", "hazard_type": "crash",
        "is_anonymous": False, "days_ago": 1,
        "title": "Minor collision blocking the right lane, Route 90 near the Dead Sea road",
        "body": "Two cars pulled over after a low-speed collision; the right lane is partly "
                "blocked. Traffic is merging left well before the scene.",
        "longitude": 35.3721, "latitude": 31.7333,
    },
    {
        "key": "seed-post-crash-2", "author_key": "seed-user-4", "hazard_type": "crash",
        "is_anonymous": False, "days_ago": 0.2,
        "title": "Multi-car incident clearing up on the Ayalon southbound",
        "body": "Emergency crews are on scene and traffic is moving again, but expect a slow "
                "stretch for the next while as everyone rubbernecks.",
        "longitude": 34.7896, "latitude": 32.0407,
    },
    {
        "key": "seed-post-other-1", "author_key": "seed-user-2", "hazard_type": "other",
        "is_anonymous": False, "days_ago": 20,
        "title": "Loose cargo debris scattered across two lanes",
        "body": "Looks like something fell off a truck — cardboard and packing material spread "
                "across the middle lanes. Not sharp, but it's a visibility hazard at night.",
        "longitude": 34.8081, "latitude": 32.0100,
    },
]

# Two or three "still there / cleared now" style confirmations per post.
SEED_COMMENTS: list[dict[str, object]] = [
    {"key": "seed-comment-1", "post_key": "seed-post-pothole-1", "author_key": "seed-user-3", "is_anonymous": False, "days_ago": 8, "body": "Still there this morning, right lane."},
    {"key": "seed-comment-2", "post_key": "seed-post-pothole-1", "author_key": "seed-user-5", "is_anonymous": False, "days_ago": 6, "body": "Someone marked it with a cone, but it's still a hard hit if you're not looking."},
    {"key": "seed-comment-3", "post_key": "seed-post-pothole-2", "author_key": "seed-user-6", "is_anonymous": False, "days_ago": 1.5, "body": "Confirmed, three separate potholes now."},
    {"key": "seed-comment-4", "post_key": "seed-post-flooding-1", "author_key": "seed-user-1", "is_anonymous": False, "days_ago": 4.7, "body": "Cleared up by this evening, should be fine now."},
    {"key": "seed-comment-5", "post_key": "seed-post-flooding-1", "author_key": "seed-user-6", "is_anonymous": True, "days_ago": 4.5, "body": "Water was back after the next storm, so it depends on the day."},
    {"key": "seed-comment-6", "post_key": "seed-post-broken-signal-1", "author_key": "seed-user-2", "is_anonymous": False, "days_ago": 6.8, "body": "City crew was working on it around midday."},
    {"key": "seed-comment-7", "post_key": "seed-post-poor-lighting-1", "author_key": "seed-user-4", "is_anonymous": False, "days_ago": 11, "body": "Reported to the municipality, no fix yet as of last week."},
    {"key": "seed-comment-8", "post_key": "seed-post-speed-bump-1", "author_key": "seed-user-2", "is_anonymous": False, "days_ago": 14, "body": "Almost bottomed out my car on this one, please add a sign."},
    {"key": "seed-comment-9", "post_key": "seed-post-crash-1", "author_key": "seed-user-5", "is_anonymous": False, "days_ago": 0.8, "body": "Lane's clear again now, just some glass left on the shoulder."},
    {"key": "seed-comment-10", "post_key": "seed-post-crash-2", "author_key": "seed-user-3", "is_anonymous": False, "days_ago": 0.1, "body": "Traffic backed up for about twenty minutes but moving now."},
    {"key": "seed-comment-11", "post_key": "seed-post-other-1", "author_key": "seed-user-5", "is_anonymous": False, "days_ago": 19, "body": "Mostly swept away by the wind, minor now."},
]

# One demo photo (a solid-color placeholder, see _solid_color_png) on most posts, so the
# feed reads as a populated, photo-driven forum rather than text-only rows.
SEED_POST_MEDIA: list[dict[str, object]] = [
    {"key": "seed-media-pothole-1", "post_key": "seed-post-pothole-1", "color": (96, 92, 88)},
    {"key": "seed-media-pothole-2", "post_key": "seed-post-pothole-2", "color": (104, 98, 84)},
    {"key": "seed-media-flooding-1", "post_key": "seed-post-flooding-1", "color": (66, 108, 148)},
    {"key": "seed-media-broken-signal-1", "post_key": "seed-post-broken-signal-1", "color": (176, 62, 48)},
    {"key": "seed-media-poor-lighting-1", "post_key": "seed-post-poor-lighting-1", "color": (40, 42, 58)},
    {"key": "seed-media-speed-bump-1", "post_key": "seed-post-speed-bump-1", "color": (70, 70, 72)},
    {"key": "seed-media-crash-1", "post_key": "seed-post-crash-1", "color": (150, 42, 40)},
]

# A handful of up/down votes; never the author voting on their own content.
SEED_VOTES: list[dict[str, object]] = [
    {"target_type": "post", "target_key": "seed-post-pothole-1", "voter_key": "seed-user-2", "value": 1},
    {"target_type": "post", "target_key": "seed-post-pothole-1", "voter_key": "seed-user-3", "value": 1},
    {"target_type": "post", "target_key": "seed-post-pothole-1", "voter_key": "seed-user-4", "value": 1},
    {"target_type": "post", "target_key": "seed-post-pothole-2", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "post", "target_key": "seed-post-pothole-2", "voter_key": "seed-user-6", "value": 1},
    {"target_type": "post", "target_key": "seed-post-flooding-1", "voter_key": "seed-user-3", "value": 1},
    {"target_type": "post", "target_key": "seed-post-flooding-1", "voter_key": "seed-user-4", "value": -1},
    {"target_type": "post", "target_key": "seed-post-broken-signal-1", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "post", "target_key": "seed-post-broken-signal-1", "voter_key": "seed-user-5", "value": 1},
    {"target_type": "post", "target_key": "seed-post-poor-lighting-1", "voter_key": "seed-user-2", "value": 1},
    {"target_type": "post", "target_key": "seed-post-speed-bump-1", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "post", "target_key": "seed-post-speed-bump-1", "voter_key": "seed-user-3", "value": -1},
    {"target_type": "post", "target_key": "seed-post-crash-1", "voter_key": "seed-user-4", "value": 1},
    {"target_type": "post", "target_key": "seed-post-crash-1", "voter_key": "seed-user-5", "value": 1},
    {"target_type": "post", "target_key": "seed-post-crash-1", "voter_key": "seed-user-6", "value": 1},
    {"target_type": "post", "target_key": "seed-post-crash-2", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "post", "target_key": "seed-post-other-1", "voter_key": "seed-user-3", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-1", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-1", "voter_key": "seed-user-4", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-3", "voter_key": "seed-user-4", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-6", "voter_key": "seed-user-5", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-8", "voter_key": "seed-user-4", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-9", "voter_key": "seed-user-1", "value": 1},
    {"target_type": "comment", "target_key": "seed-comment-10", "voter_key": "seed-user-6", "value": 1},
]


def _seed_users(connection: psycopg.Connection[dict]) -> dict[str, int]:
    user_ids: dict[str, int] = {}
    for user in SEED_USERS:
        row = connection.execute(
            """
            INSERT INTO app.users
                (email, password_hash, driving_experience, vehicle_type,
                 avoid_tolls, avoid_highways, is_seed_account)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE)
            ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
            RETURNING id
            """,
            (
                user["email"], _SEED_PASSWORD_HASH, user["driving_experience"],
                user["vehicle_type"], user["avoid_tolls"], user["avoid_highways"],
            ),
        ).fetchone()
        user_ids[str(user["key"])] = row["id"]
    return user_ids


def _seed_posts(connection: psycopg.Connection[dict], user_ids: dict[str, int]) -> dict[str, UUID]:
    post_ids: dict[str, UUID] = {}
    for post in SEED_POSTS:
        post_id = _seed_uuid(str(post["key"]))
        post_ids[str(post["key"])] = post_id
        connection.execute(
            """
            INSERT INTO app.forum_posts
                (id, author_user_id, is_anonymous, hazard_type, title, body,
                 longitude, latitude, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                post_id, user_ids[str(post["author_key"])], post["is_anonymous"],
                post["hazard_type"], post["title"], post["body"],
                post["longitude"], post["latitude"],
                _days_ago(float(post["days_ago"])), _days_ago(float(post["days_ago"])),
            ),
        )
    return post_ids


def _seed_post_media(connection: psycopg.Connection[dict], post_ids: dict[str, UUID]) -> int:
    """Writes each demo image to disk and inserts its row, but only the first time — unlike
    posts/comments' plain INSERT ... ON CONFLICT DO NOTHING, this must check for the row
    before writing the file too, since re-running would otherwise leak an orphaned file on
    every container restart even though the (idempotent) DB insert itself would no-op."""
    settings = get_settings()
    seeded = 0
    for media in SEED_POST_MEDIA:
        media_id = _seed_uuid(str(media["key"]))
        already_seeded = connection.execute(
            "SELECT 1 FROM app.forum_post_media WHERE id = %s", (media_id,)
        ).fetchone()
        if already_seeded is not None:
            continue
        png_bytes = _solid_color_png(640, 400, media["color"])  # type: ignore[arg-type]
        storage_key = write_media_file(settings, png_bytes)
        connection.execute(
            """
            INSERT INTO app.forum_post_media
                (id, post_id, media_type, storage_key, content_type, byte_size)
            VALUES (%s, %s, 'image', %s, 'image/png', %s)
            """,
            (media_id, post_ids[str(media["post_key"])], storage_key, len(png_bytes)),
        )
        seeded += 1
    return seeded


def _seed_comments(
    connection: psycopg.Connection[dict], user_ids: dict[str, int], post_ids: dict[str, UUID]
) -> dict[str, UUID]:
    comment_ids: dict[str, UUID] = {}
    for comment in SEED_COMMENTS:
        comment_id = _seed_uuid(str(comment["key"]))
        comment_ids[str(comment["key"])] = comment_id
        connection.execute(
            """
            INSERT INTO app.forum_comments
                (id, post_id, author_user_id, is_anonymous, body, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                comment_id, post_ids[str(comment["post_key"])],
                user_ids[str(comment["author_key"])], comment["is_anonymous"], comment["body"],
                _days_ago(float(comment["days_ago"])), _days_ago(float(comment["days_ago"])),
            ),
        )
    return comment_ids


def _seed_votes(
    connection: psycopg.Connection[dict],
    user_ids: dict[str, int],
    post_ids: dict[str, UUID],
    comment_ids: dict[str, UUID],
) -> None:
    for vote in SEED_VOTES:
        target_id = (
            post_ids[str(vote["target_key"])]
            if vote["target_type"] == "post"
            else comment_ids[str(vote["target_key"])]
        )
        connection.execute(
            """
            INSERT INTO app.forum_votes (user_id, target_type, target_id, value)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, target_type, target_id) DO NOTHING
            """,
            (user_ids[str(vote["voter_key"])], vote["target_type"], target_id, vote["value"]),
        )


def _recompute_counters(connection: psycopg.Connection[dict]) -> None:
    """Recompute denormalized counters from the actual seeded rows, so the seed step stays
    correct even if SEED_VOTES/SEED_COMMENTS change without a matching manual count update."""
    connection.execute(
        """
        UPDATE app.forum_posts p SET
            comment_count = (
                SELECT count(*) FROM app.forum_comments c
                WHERE c.post_id = p.id AND c.status = 'active'
            ),
            upvote_count = (
                SELECT count(*) FROM app.forum_votes v
                WHERE v.target_type = 'post' AND v.target_id = p.id AND v.value = 1
            ),
            downvote_count = (
                SELECT count(*) FROM app.forum_votes v
                WHERE v.target_type = 'post' AND v.target_id = p.id AND v.value = -1
            )
        WHERE p.id = ANY(%s)
        """,
        ([_seed_uuid(str(post["key"])) for post in SEED_POSTS],),
    )
    connection.execute(
        """
        UPDATE app.forum_comments c SET
            upvote_count = (
                SELECT count(*) FROM app.forum_votes v
                WHERE v.target_type = 'comment' AND v.target_id = c.id AND v.value = 1
            ),
            downvote_count = (
                SELECT count(*) FROM app.forum_votes v
                WHERE v.target_type = 'comment' AND v.target_id = c.id AND v.value = -1
            )
        WHERE c.id = ANY(%s)
        """,
        ([_seed_uuid(str(comment["key"])) for comment in SEED_COMMENTS],),
    )


def _backfill_missing_triage(connection: psycopg.Connection[dict]) -> None:
    """Enqueue triage for every active post that was never classified — not scoped to this
    run's seeded posts, deliberately: this also catches real (non-seed) posts created before the
    LLM feature existed, or any post whose triage job failed to ever get enqueued. The NOT EXISTS
    guard skips posts that already have a queued/running triage job, so calling this on every
    container start (seed_forum_demo_data.py runs at every startup, not just the first) never
    piles up duplicate jobs for the same post while a previous attempt is still in flight — a
    genuinely failed attempt is retried on the next start, which is the intended self-healing
    behavior. Fail-open (PRD decision 6): a Redis/broker problem here must never fail the seed
    step the rest of container startup depends on — the caller wraps this in a bare except."""
    from app.llm.tasks import enqueue_triage

    rows = connection.execute(
        """
        SELECT p.id, p.body FROM app.forum_posts p
        WHERE p.status = 'active'
          AND p.llm_hazard_type_suggested IS NULL
          AND p.llm_severity IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM app.llm_jobs j
              WHERE j.subject_post_id = p.id
                AND j.kind = 'triage'
                AND j.status IN ('queued', 'running')
          )
        """
    ).fetchall()
    for row in rows:
        enqueue_triage(connection, subject_post_id=str(row["id"]), input_chars=len(row["body"]))


def _backfill_missing_dedup_checks(connection: psycopg.Connection[dict]) -> None:
    """Enqueue a dedup check for every active, already-triaged post that has never had one
    attempted — not scoped to this run's seeded posts, for the same reason as
    _backfill_missing_triage. Also covers a real gap found via live usage: posts created without
    coordinates never got a dedup job at all until the author-scoped fallback was added to
    `enqueue_dedup_check_if_applicable` (see app/llm/tasks.py's _find_dedup_candidates_for_post),
    so any such post that predates that fix needs a first attempt now. Unlike the triage backfill,
    a post that already has a dedup_check job in *any* state (including 'failed') is skipped —
    dedup is a secondary enrichment on top of triage, and retrying failures indefinitely on every
    restart risks masking a real, persistent problem rather than a one-off startup race."""
    from app.llm.tasks import enqueue_dedup_check_if_applicable

    rows = connection.execute(
        """
        SELECT p.id FROM app.forum_posts p
        WHERE p.status = 'active'
          AND p.llm_hazard_type_suggested IS NOT NULL
          AND p.duplicate_of_post_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM app.llm_jobs j
              WHERE j.subject_post_id = p.id AND j.kind = 'dedup_check'
          )
        """
    ).fetchall()
    for row in rows:
        enqueue_dedup_check_if_applicable(connection, str(row["id"]))


def seed_forum_demo_data(database_url: str) -> dict[str, int]:
    with psycopg.connect(synchronous_database_url(database_url), row_factory=dict_row) as connection:
        with connection.transaction():
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('app.forum-demo-seed'))")
            user_ids = _seed_users(connection)
            post_ids = _seed_posts(connection, user_ids)
            _seed_post_media(connection, post_ids)
            comment_ids = _seed_comments(connection, user_ids, post_ids)
            _seed_votes(connection, user_ids, post_ids, comment_ids)
            _recompute_counters(connection)
        try:
            _backfill_missing_triage(connection)
        except Exception:
            pass
        try:
            _backfill_missing_dedup_checks(connection)
        except Exception:
            pass
    # Stable totals only (not "rows inserted this run"), so the report is identical across
    # repeated idempotent runs and can be compared directly by callers/tests. Deliberately
    # excludes any triage-backfill count: how many posts still lack classification varies from
    # moment to moment as async jobs complete, so it can never be a "stable total" like the rest
    # of this dict — see _backfill_missing_triage's own NOT EXISTS guard for how duplicates are
    # avoided without needing to report progress here.
    return {
        "users": len(user_ids),
        "posts": len(post_ids),
        "comments": len(comment_ids),
        "media": len(SEED_POST_MEDIA),
        "votes": len(SEED_VOTES),
    }


def main() -> None:
    report = seed_forum_demo_data(os.environ["DATABASE_URL"])
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
