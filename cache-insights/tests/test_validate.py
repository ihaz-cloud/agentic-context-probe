"""Tests for cache_insights.validate against the §6.1 result schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from cache_insights import validate


def test_valid_result_passes(fixtures_dir: Path):
    record = json.loads((fixtures_dir / "result-cold-warm.json").read_text())
    validate.validate_result(record)  # should not raise


def test_invalid_result_missing_required(fixtures_dir: Path):
    record = json.loads((fixtures_dir / "result-invalid.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        validate.validate_result(record)


def test_invalid_vendor_enum(fixtures_dir: Path):
    record = json.loads((fixtures_dir / "result-cold-warm.json").read_text())
    record["vendor"] = "totally-fake-vendor"
    with pytest.raises(jsonschema.ValidationError, match="enum"):
        validate.validate_result(record)


def test_invalid_test_type_enum(fixtures_dir: Path):
    record = json.loads((fixtures_dir / "result-cold-warm.json").read_text())
    record["test_type"] = "made_up"
    with pytest.raises(jsonschema.ValidationError):
        validate.validate_result(record)


def test_request_missing_required_field(fixtures_dir: Path):
    record = json.loads((fixtures_dir / "result-cold-warm.json").read_text())
    del record["requests"][0]["cached_tokens"]
    with pytest.raises(jsonschema.ValidationError, match="cached_tokens"):
        validate.validate_result(record)


def test_load_schema_caches():
    """Schema is loaded from disk on first call and cached thereafter."""
    s1 = validate.load_schema()
    s2 = validate.load_schema()
    assert s1 is s2  # same object, lru_cache hit
