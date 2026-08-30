"""DEAD — UNUSED as of 2026-08-28. Crew memory is now disabled (crew.jsonc
"memory": false) and this callback is no longer registered in
before_kickoff_callbacks. Kept for reference: it documents a real
cross-product contamination incident and the fix approach, in case memory is
ever re-enabled with proper per-product MemoryScope. Do not re-register
without re-enabling "memory" in crew.jsonc first.

before_kickoff_callback: clear crew memory when the product changes.

WHY THIS IS NECESSARY (not just hygiene — a correctness fix):

CrewAI injects a top-5 memory recall into EVERY task's prompt automatically,
with no product scoping (see the "memory" note in crew.jsonc). Because past
runs save notes phrased as instructions — e.g. "The visual brief should focus
on showcasing the Camera Control button and Action Button" — a later run for
a different product receives those as authoritative-sounding guidance inside
its own context and follows them.

Demonstrated live on 2026-08-26: a Nike run's visual_brief_task recall
returned 2 genuine Nike memories mixed with 2 iPhone memories and 1 Nutella
memory, and produced a Nike visual brief whose PRIMARY subject was a snack,
with "Camera Control button", "Action Button", "#iPhone16" and
"#ClassicCulinaryComfort" folded in. Prompt-level instructions telling the
agent to ignore contamination were already in place at the time and did not
prevent it — an instruction-shaped memory in-context beats a "please ignore
irrelevant memories" rule on a 7B local model.

Proper per-product scoping (MemoryScope) exists in CrewAI but is not
reachable from JSONC config; it needs a custom Python driver that rebuilds
each agent's `.memory` after {product_name} is known. Until that's built,
this callback keeps memory useful WITHIN a run (tasks still share context via
task context chaining) while preventing cross-product bleed: it wipes the
store whenever the product differs from the last run's product.

Same-product reruns keep their memory, so per-product continuity still works
for repeated runs of the same product.
"""

import json
import os
from pathlib import Path

import lancedb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAST_PRODUCT_FILE = PROJECT_ROOT / ".last_product.json"


def _memory_db_path() -> Path | None:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not local_appdata:
        return None
    from crewai.project.json_loader import load_jsonc_file

    crew_def = load_jsonc_file(PROJECT_ROOT / "crew.jsonc")
    project_name = crew_def.get("name")
    if not project_name:
        return None
    return Path(local_appdata) / "CrewAI" / project_name / "memory"


def _read_last_product() -> str | None:
    try:
        return json.loads(LAST_PRODUCT_FILE.read_text(encoding="utf-8")).get("product")
    except (FileNotFoundError, ValueError, AttributeError):
        return None


def _write_last_product(product: str) -> None:
    try:
        LAST_PRODUCT_FILE.write_text(
            json.dumps({"product": product}), encoding="utf-8"
        )
    except OSError:
        pass


def reset_memory_for_product(inputs: dict) -> dict:
    product = str(inputs.get("product_name", "")).strip().lower()
    if not product:
        return inputs

    if _read_last_product() == product:
        return inputs  # same product as last run — keep its memory

    try:
        db_path = _memory_db_path()
        if db_path is not None and db_path.exists():
            db = lancedb.connect(str(db_path))
            if "memories" in db.table_names():
                tbl = db.open_table("memories")
                if tbl.count_rows():
                    tbl.delete("true")
    except Exception:
        # Best-effort maintenance — never block a real kickoff over it.
        pass

    _write_last_product(product)
    return inputs
