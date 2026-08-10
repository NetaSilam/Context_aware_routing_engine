from __future__ import annotations

from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent / "app"
_WATCHED_MODULES = ("forum", "messaging", "notifications")


def test_forum_dm_and_notification_modules_never_call_the_logging_module() -> None:
    # Post/comment/DM bodies and media bytes are user content, never operational metadata.
    # The simplest way to guarantee they can never reach a log line is to guarantee these
    # modules never call `logging` at all (unlike app/routing/route_jobs.py, which logs
    # structured, content-free events such as job_id/stage/error_code).
    offending = []
    for module_name in _WATCHED_MODULES:
        for path in (_APP_ROOT / module_name).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            if "logging" in source or "logger" in source.lower():
                offending.append(str(path.relative_to(_APP_ROOT.parent)))
    assert offending == []
