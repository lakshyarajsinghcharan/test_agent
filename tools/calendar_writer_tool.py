"""Single-purpose write tool for content_calendar.md.

Replaces FileWriterTool for schedule_task specifically. That tool's generic
filename/content/overwrite schema gave the model three ways to fail a write:
wrong argument name (filename vs. file_path, copied from FileReadTool),
forgetting the directory defaults to project root, and forgetting
overwrite=True on a retry (observed live: attempt 1 passed overwrite=True,
attempt 2 dropped it and the write silently no-opped with an error the model
then misread as a brand-check failure). This tool takes only `content` and
hardcodes the filename, directory, and overwrite — none of those failure
modes are reachable anymore because the model no longer controls them.

Also refuses to write content with a non-PASS Brand Check Status. Live run,
2026-08-26: brand_check_task returned FAIL, but schedule_task still called
this tool with a full calendar entry (self-contradictorily including "Brand
Check Status: FAIL" in the entry) BEFORE producing its final "NOT SCHEDULED"
text. schedule_guardrail.py only validates that final text — it has no
visibility into tool calls that already happened during the same generation,
so the corrupted write landed on disk even though the guardrail correctly
accepted the eventual (correct) NOT SCHEDULED answer. Enforcing this in the
tool itself, not just the post-hoc guardrail, closes that gap: bad content
now can't reach disk regardless of what the model's final text says.

APPEND-ONLY as of 2026-08-29 (calendar-clobber fix). This tool used to take
the WHOLE file text — existing entries plus the new one — and overwrite with
it, trusting the model to faithfully re-emit prior entries it was shown as
{existing_calendar}. It didn't: a Tesla Model 3 run passed brand check and
wrote ONLY its own entry, silently destroying the prior Apple/iPhone 13 entry.
"Never drop prior entries" was prompt-only guidance with zero enforcement, and
schedule_guardrail.py couldn't catch it either — that guardrail shape-checks
only the NEW entry and never diffs against what was on disk. Now the tool
takes ONLY the new entry and does the appending itself by reading the current
file, so dropping prior history is not a reachable failure mode: the model
never supplies the old text at all. Same philosophy as the argument hardening
above — take control away from the model rather than instruct it harder.
"""

import re
from pathlib import Path

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

CALENDAR_PATH = Path(__file__).resolve().parent.parent / "content_calendar.md"

_STATUS_RE = re.compile(r"Brand Check Status[\s*_]*:\s*\**\s*([^\n]+)", re.IGNORECASE)
_CAPTION_RE = re.compile(r"Caption[\s*_]*:\s*\**\s*([^\n]+)", re.IGNORECASE)

# Every entry must carry all five labeled fields. Enforced here (2026-08-29)
# after a live run wrote a bare comma-separated row instead:
#   "Dyson V15 Detect, You vacuum with..., Show a person..., PASS, 2026-08-30"
# The model's FINAL ANSWER text that run was correctly labeled, so
# schedule_guardrail.py — which only inspects that final text — passed it,
# while the tool call it had already made carried the unlabeled form. Two
# consequences: the file's format silently diverged from every other entry,
# and the caption-based dedupe below could not find a "Caption:" label to
# match on, so a retry appended the same entry a second time. Validating the
# shape in the tool closes both, since the tool sees what actually gets
# written rather than what the model says it wrote.
_REQUIRED_FIELDS = [
    "Product Name",
    "Caption",
    "Visual Brief",
    "Brand Check Status",
    "Suggested Post Date",
]


def _normalize(text: str) -> str:
    """Loose comparison key — ignores markdown emphasis and whitespace noise."""
    return re.sub(r"[\s*_]+", " ", text).strip().lower()


class CalendarWriterToolInput(BaseModel):
    content: str = Field(
        ...,
        description=(
            "ONLY the new calendar entry to append (Product Name, Caption, "
            "Visual Brief, Brand Check Status, Suggested Post Date). Do NOT "
            "include existing entries — this tool appends to them for you."
        ),
    )


class CalendarWriterTool(BaseTool):
    name: str = "Calendar Writer Tool"
    description: str = (
        "Appends one new entry to content_calendar.md. Takes a single argument, "
        "content: ONLY the new entry's text. Existing entries are preserved "
        "automatically — do not pass them in, and do not try to rewrite the "
        "whole file. Refuses to write if the entry's Brand Check Status is not "
        "PASS, and skips writing if an identical caption is already present."
    )
    args_schema: type[BaseModel] = CalendarWriterToolInput

    def _run(self, content: str) -> str:
        entry = content.strip()
        if not entry:
            return "Refused to write: the new entry was empty."

        missing = [
            field
            for field in _REQUIRED_FIELDS
            if not re.search(rf"{re.escape(field)}[\s*_]*:", entry, re.IGNORECASE)
        ]
        if missing:
            return (
                "Refused to write: the entry is not in the required labeled "
                f"format — missing field label(s): {', '.join(missing)}. Do NOT "
                "send a comma-separated row. Every entry must be five labeled "
                "markdown lines, exactly like this:\n"
                "- **Product Name**: <name>\n"
                "- **Caption**: <caption>\n"
                "- **Visual Brief**: <brief>\n"
                "- **Brand Check Status**: PASS\n"
                "- **Suggested Post Date**: TBD\n"
                "Resend the entry in that exact shape. This is a formatting "
                "problem only — it is NOT a brand-check failure, so do not "
                "answer NOT SCHEDULED because of it."
            )

        for match in _STATUS_RE.finditer(entry):
            status = match.group(1).strip().strip("*_. \t").lower()
            if status != "pass":
                return (
                    f"Refused to write: this content contains a 'Brand Check "
                    f"Status' of '{status}', not 'PASS'. This tool only ever "
                    f"writes entries that have genuinely passed brand check. "
                    f"If the verdict was FAIL, do not call this tool at all — "
                    f"just answer with the NOT SCHEDULED text and stop."
                )

        existing = ""
        if CALENDAR_PATH.exists():
            existing = CALENDAR_PATH.read_text(encoding="utf-8").strip()

        # Dedupe on caption text: a guardrail retry can re-call this tool with
        # the same entry, and appending blindly would duplicate it.
        if existing:
            new_caption = _CAPTION_RE.search(entry)
            if new_caption:
                key = _normalize(new_caption.group(1))
                for prior in _CAPTION_RE.finditer(existing):
                    if _normalize(prior.group(1)) == key:
                        return (
                            "Entry already present in content_calendar.md "
                            "(identical caption found) — nothing appended, "
                            "prior entries left intact."
                        )
            # Fallback: catch a byte-identical repeat even if the caption label
            # somehow didn't parse, so a retry can never double-append.
            if _normalize(entry) in _normalize(existing):
                return (
                    "Entry already present in content_calendar.md (identical "
                    "text found) — nothing appended, prior entries left intact."
                )

        combined = f"{existing}\n\n{entry}\n" if existing else f"{entry}\n"
        CALENDAR_PATH.write_text(combined, encoding="utf-8")

        prior_count = existing.count("Product Name") if existing else 0
        return (
            f"New entry appended to content_calendar.md. "
            f"{prior_count} prior entr{'y' if prior_count == 1 else 'ies'} preserved."
        )
