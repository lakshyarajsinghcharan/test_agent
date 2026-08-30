"""before_kickoff_callback: inject content_calendar.md's content as an input.

Lets schedule_task reference {existing_calendar} as literal text instead of
calling FileReadTool itself — removes one Thought/Action/Observation round
trip from the Scheduler's tool loop (see crew.jsonc's schedule_task comment).

Also caps how large content_calendar.md is allowed to grow. It's a
read-modify-write file the Scheduler re-injects and rewrites on every
successful run, so its size (and therefore this task's prompt size) would
otherwise grow forever the more the crew is used. Individual entries are
free-form LLM-authored markdown, not a fixed schema, so rather than parse
entry boundaries (fragile), this rotates the whole file to an append-only
archive once it crosses a size threshold and starts a fresh small one — a
size-based reset instead of an entry-count trim, but it bounds prompt growth
the same way, and the archive still preserves full history (just never
re-injected into any prompt).
"""

from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CALENDAR_PATH = PROJECT_ROOT / "content_calendar.md"
ARCHIVE_PATH = PROJECT_ROOT / "content_calendar_archive.md"
NO_CALENDAR_YET = "(no content_calendar.md yet — this will be the first entry)"
MAX_CALENDAR_CHARS = 4000


def _rotate_if_too_large(content: str) -> str:
    if len(content) <= MAX_CALENDAR_CHARS:
        return content

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    archive_entry = f"\n\n<!-- rotated {timestamp} -->\n{content}\n"
    with ARCHIVE_PATH.open("a", encoding="utf-8") as f:
        f.write(archive_entry)

    return f"(older entries archived to content_calendar_archive.md as of {timestamp})"


def inject_existing_calendar(inputs: dict) -> dict:
    try:
        existing = CALENDAR_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        existing = ""

    if existing:
        rotated = _rotate_if_too_large(existing)
        if rotated != existing:
            CALENDAR_PATH.write_text(rotated + "\n", encoding="utf-8")
        existing = rotated

    return {
        **inputs,
        "existing_calendar": existing if existing else NO_CALENDAR_YET,
    }
