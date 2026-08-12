#!/usr/bin/env python3
"""Validate an IPW operation-sequence submission without scoring it."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


PART_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
FILENAME_RES = {
    "easy": re.compile(r"^(?P<part_id>[A-Za-z0-9][A-Za-z0-9_-]*)_sequence\.json$"),
    "hard": re.compile(r"^(?P<part_id>[A-Za-z0-9][A-Za-z0-9_-]*)_tools\.json$"),
}


def load_vocabularies(vocabulary_path: Path) -> dict[str, set[str]]:
    """Read the canonical label vocabularies bundled with the evaluation harness."""
    try:
        vocabularies = json.loads(vocabulary_path.read_text(encoding="utf-8"))
        return {
            "o1": set(vocabularies["o1"]),
            "o2": set(vocabularies["o2"]),
            "tool_type": set(vocabularies["tool_type"]),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"could not read vocabularies from {vocabulary_path}: {error}") from error


def require_exact_keys(value: dict[str, Any], expected: set[str], location: str, errors: list[str]) -> None:
    keys = set(value)
    missing = sorted(expected - keys)
    unexpected = sorted(keys - expected)
    if missing:
        errors.append(f"{location}: missing required field(s): {', '.join(missing)}.")
    if unexpected:
        errors.append(f"{location}: unexpected field(s): {', '.join(unexpected)}.")


def validate_submission(
    submission_path: Path,
    difficulty: str,
    vocabularies: dict[str, set[str]],
) -> list[str]:
    """Return format errors. Sequence length is intentionally never compared to truth."""
    errors: list[str] = []
    suffix = "sequence" if difficulty == "easy" else "tools"
    match = FILENAME_RES[difficulty].fullmatch(submission_path.name)
    if not match:
        errors.append(
            f"filename must be '<part_id>_{suffix}.json', "
            f"for example 'featured_part_00001_{suffix}.json'."
        )

    try:
        payload = json.loads(submission_path.read_text(encoding="utf-8"))
    except OSError as error:
        return [f"could not read submission: {error}"]
    except json.JSONDecodeError as error:
        return [f"invalid JSON at line {error.lineno}, column {error.colno}: {error.msg}."]

    if not isinstance(payload, dict):
        return ["top-level JSON value must be an object."]

    require_exact_keys(payload, {"part_id", "summary", "operations"}, "top level", errors)
    part_id = payload.get("part_id")
    if not isinstance(part_id, str) or not PART_ID_RE.fullmatch(part_id):
        errors.append("top level 'part_id' must be a non-empty identifier using letters, digits, '_' or '-'.")
    elif match and match.group("part_id") != part_id:
        errors.append(
            f"filename part id '{match.group('part_id')}' does not match JSON part_id '{part_id}'."
        )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        errors.append("top level 'summary' must be an object.")
    else:
        require_exact_keys(summary, {"number_of_operations"}, "summary", errors)
        declared_count = summary.get("number_of_operations")
        if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count < 0:
            errors.append("summary.number_of_operations must be a non-negative integer.")
        else:
            operations = payload.get("operations")
            if isinstance(operations, list) and declared_count != len(operations):
                errors.append(
                    "summary.number_of_operations must equal the number of submitted operations."
                )

    operations = payload.get("operations")
    if not isinstance(operations, list):
        errors.append("top level 'operations' must be an array.")
        return errors

    expected_keys = (
        {"operation_number", "o1", "o2"}
        if difficulty == "easy"
        else {"operation_number", "tool_type", "tool_diameter_mm"}
    )
    for index, operation in enumerate(operations, start=1):
        location = f"operations[{index - 1}]"
        if not isinstance(operation, dict):
            errors.append(f"{location} must be an object.")
            continue
        require_exact_keys(operation, expected_keys, location, errors)
        operation_number = operation.get("operation_number")
        if operation_number != index:
            errors.append(f"{location}.operation_number must be {index}.")

        if difficulty == "easy":
            for field in ("o1", "o2"):
                value = operation.get(field)
                if not isinstance(value, str) or value not in vocabularies[field]:
                    allowed = ", ".join(sorted(vocabularies[field]))
                    errors.append(f"{location}.{field} must be one of: {allowed}.")
        else:
            tool_type = operation.get("tool_type")
            if not isinstance(tool_type, str) or tool_type not in vocabularies["tool_type"]:
                allowed = ", ".join(sorted(vocabularies["tool_type"]))
                errors.append(f"{location}.tool_type must be one of: {allowed}.")
            diameter = operation.get("tool_diameter_mm")
            if isinstance(diameter, bool) or not isinstance(diameter, (int, float)):
                errors.append(f"{location}.tool_diameter_mm must be a positive number in mm.")
            elif not math.isfinite(diameter) or diameter <= 0:
                errors.append(f"{location}.tool_diameter_mm must be a finite positive number in mm.")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check an IPW sequence submission's filename and JSON format.")
    parser.add_argument("submission", type=Path, help="JSON prediction file to validate")
    parser.add_argument("--difficulty", choices=("easy", "hard"), required=True)
    parser.add_argument(
        "--vocabularies",
        type=Path,
        default=Path(__file__).with_name("vocabularies.json"),
        help="JSON file that defines the accepted vocabularies",
    )
    arguments = parser.parse_args()

    try:
        vocabularies = load_vocabularies(arguments.vocabularies)
    except ValueError as error:
        print(f"INVALID: {error}")
        return 2

    errors = validate_submission(arguments.submission, arguments.difficulty, vocabularies)
    if errors:
        print(f"INVALID: {arguments.submission.name}")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        f"VALID: {arguments.submission.name} is a correctly formatted "
        f"{arguments.difficulty} submission."
    )
    print("No ground-truth sequence length check was performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())