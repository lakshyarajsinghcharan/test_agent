"""Deterministic shape check for schedule_task output — no LLM judge involved."""

import re

FAIL_PREFIX = "NOT SCHEDULED - Brand check failed"
REQUIRED_FIELDS = [
    "Product name",
    "Caption",
    "Visual Brief",
    "Brand Check Status",
    "Suggested Post Date",
]


def validate_schedule_output(task_output):
    raw = task_output.raw.strip()
    is_fail_shape = raw.startswith(FAIL_PREFIX)

    # [\s*_]* (not just \s*) between the label and the colon: markdown bold
    # commonly closes the ** BEFORE the colon ("**Product Name**:"), not just
    # after it ("**Product Name:**") — a real model output used the former
    # and \s* alone silently failed to match any of the 5 fields.
    present_fields = [
        field
        for field in REQUIRED_FIELDS
        if re.search(rf"{re.escape(field)}[\s*_]*:", raw, re.IGNORECASE)
    ]
    has_all_fields = len(present_fields) == len(REQUIRED_FIELDS)

    status_match = re.search(
        r"Brand Check Status[\s*_]*:\s*\**\s*([^\n]+)", raw, re.IGNORECASE
    )
    status_value = (
        status_match.group(1).strip().strip("*_. \t").lower()
        if status_match
        else None
    )
    has_pass_status = status_value == "pass"

    if is_fail_shape and present_fields:
        return False, (
            f"Blends both shapes: starts with '{FAIL_PREFIX}' but also contains "
            f"calendar field(s) ({', '.join(present_fields)})."
        )

    if is_fail_shape:
        reasoning = raw[len(FAIL_PREFIX):].strip(" -\n\t")
        if not reasoning:
            return False, "Starts with the correct FAIL text but has no reasoning after it."
        return True, raw

    if has_all_fields:
        if not has_pass_status:
            shown = status_value if status_value else "missing"
            return False, (
                f"Calendar entry is well-formed but Brand Check Status is "
                f"'{shown}', not 'PASS'."
            )
        return True, raw

    if present_fields:
        missing = [f for f in REQUIRED_FIELDS if f not in present_fields]
        return False, f"Calendar entry is missing required field(s): {', '.join(missing)}."

    return False, (
        "Output matches neither valid shape: not a well-formed PASS calendar "
        f"entry, and does not start with '{FAIL_PREFIX}'."
    )
