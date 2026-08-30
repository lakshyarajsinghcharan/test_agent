"""DEAD — UNUSED as of 2026-08-28. Crew memory is now disabled (crew.jsonc
"memory": false), so there is no live memory store to wipe. Kept for
reference in case memory is ever re-enabled.

Standalone maintenance script: wipe the crew's persistent memory store.

NOT wired into before_kickoff_callbacks — run manually (python hooks/wipe_memory.py)
before switching to a genuinely different product category during testing.

True per-product scoping (so Nutella and RTX 4060 memories never mix, without
ever needing a manual wipe) is supported by CrewAI's MemoryScope but requires
moving off `crewai run`/pure-JSONC to a custom driver script that rebuilds
each agent's `.memory` after {product_name} is known — see the crew.jsonc
"memory" field comment. This script is the practical short-term stand-in:
treat memory as session-level, reset it between unrelated product tests.
"""

import os
from pathlib import Path

import lancedb


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


def wipe_memory() -> int:
    """Delete every row in the memory store. Returns the number of rows removed."""
    db_path = _memory_db_path()
    if db_path is None or not db_path.exists():
        return 0

    db = lancedb.connect(str(db_path))
    if "memories" not in db.table_names():
        return 0
    tbl = db.open_table("memories")
    count = tbl.count_rows()
    if count:
        tbl.delete("true")
    return count


if __name__ == "__main__":
    removed = wipe_memory()
    print(f"Wiped {removed} memory record(s).")
