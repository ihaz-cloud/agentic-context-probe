"""Result-record validator for the §6.1 schema."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).parent / "schemas" / "result.schema.json"


@lru_cache(maxsize=1)
def load_schema() -> dict:
    """Load and cache the §6.1 result schema from disk."""
    with SCHEMA_PATH.open() as f:
        return json.load(f)


def validate_result(record: dict) -> None:
    """Validate a result record against the §6.1 schema.

    Raises jsonschema.ValidationError on invalid input.
    """
    jsonschema.validate(instance=record, schema=load_schema())
