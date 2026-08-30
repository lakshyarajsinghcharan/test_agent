"""DEAD — UNUSED as of 2026-08-28. Crew memory is now disabled (crew.jsonc
"memory": false) and this callback is no longer registered in
before_kickoff_callbacks. Kept for reference in case memory is ever
re-enabled. Do not re-register without re-enabling "memory" in crew.jsonc
first.

before_kickoff_callback: cap the crew's persistent memory store.

The LanceDB memory store grows unboundedly across every run and is never
pruned by CrewAI itself — measured on 2026-08-18 at 287 entries / 152K chars
total, including one single 36,581-char entry. recall() only returns top-5
matches per query so a huge store isn't an immediate correctness problem, but
it grows storage and query cost forever and outlier entries like that one
have no business being in a "short semantic note" memory system. This prunes
oversized entries outright and caps total row count (oldest first) before
every kickoff, so it never gets worse than these bounds.
"""

import os
from pathlib import Path

import lancedb

MAX_ENTRY_CHARS = 2000
MAX_TOTAL_ENTRIES = 200


def _memory_db_path() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    from crewai.project.json_loader import load_jsonc_file

    project_root = Path(__file__).resolve().parent.parent
    crew_def = load_jsonc_file(project_root / "crew.jsonc")
    project_name = crew_def.get("name")
    if not project_name:
        return None
    return Path(local_appdata) / "CrewAI" / project_name / "memory"


def prune_memory(inputs: dict) -> dict:
    db_path = _memory_db_path()
    if db_path is None or not db_path.exists():
        return inputs

    try:
        db = lancedb.connect(str(db_path))
        if "memories" not in db.table_names():
            return inputs
        tbl = db.open_table("memories")

        tbl.delete(f"length(content) > {MAX_ENTRY_CHARS}")

        remaining = tbl.count_rows()
        if remaining > MAX_TOTAL_ENTRIES:
            created = sorted(tbl.to_arrow().column("created_at").to_pylist())
            cutoff = created[remaining - MAX_TOTAL_ENTRIES]
            tbl.delete(f"created_at < '{cutoff}'")
    except Exception:
        # Pruning is best-effort maintenance — never block a real kickoff over it.
        pass

    return inputs
