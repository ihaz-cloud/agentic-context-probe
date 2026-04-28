"""Codex OTLP logs parser — read per-turn cache attribution from the OTel collector output."""

from __future__ import annotations

from pathlib import Path

from cache_insights.parsers._io import iter_jsonl_records

CODEX_LOGS_FILE = Path("/tmp/otel-data/codex-logs.jsonl")

CODEX_SERVICE_NAME = "codex_exec"

REQUIRED_TOKEN_FIELDS = (
    "input_token_count",
    "cached_token_count",
    "output_token_count",
)

# Codex CLI 0.122.0 quirk: positive token counts arrive as {"stringValue": "8808"}
# while zero counts arrive as {"intValue": "0"}. Coerce all known token-count
# fields to int regardless of which envelope was used.
INT_COERCE_FIELDS = (
    "input_token_count",
    "cached_token_count",
    "output_token_count",
    "reasoning_token_count",
    "tool_token_count",
    "duration_ms",
)


def _otlp_attrs_to_dict(attr_list: list[dict]) -> dict:
    """Flatten an OTLP attributes array into a dict, unwrapping value envelopes.

    OTLP encodes attribute values as {key: ..., value: {<typed>: ...}} where
    <typed> is one of intValue, stringValue, doubleValue, boolValue. intValue
    arrives as a JSON string per the spec — cast on extraction.
    """
    out: dict = {}
    for a in attr_list or []:
        key = a.get("key")
        if key is None:
            continue
        v = a.get("value", {})
        if "intValue" in v:
            out[key] = int(v["intValue"])
        elif "stringValue" in v:
            out[key] = v["stringValue"]
        elif "doubleValue" in v:
            out[key] = float(v["doubleValue"])
        elif "boolValue" in v:
            out[key] = bool(v["boolValue"])
        else:
            out[key] = v
    return out


def _resource_is_codex(resource: dict) -> bool:
    attrs = _otlp_attrs_to_dict(resource.get("attributes", []))
    return attrs.get("service.name") == CODEX_SERVICE_NAME


def parse_last_turn(log_path: Path | None = None) -> dict:
    """Return the last Codex log-record's token usage from the collector output.

    Args:
        log_path: explicit path to the collector's log file. Defaults to
            /tmp/otel-data/codex-logs.jsonl.

    Returns:
        Dict with input_tokens, output_tokens, cached_tokens, reasoning_tokens,
        tool_tokens, model, _source_file.

    Raises:
        FileNotFoundError if the log file does not exist.
        ValueError if no Codex usage record is found.
    """
    path = Path(log_path) if log_path is not None else CODEX_LOGS_FILE
    if not path.exists():
        raise FileNotFoundError(f"Codex OTel log not found at {path}")

    last_match: dict | None = None
    for rec in iter_jsonl_records(path):
        for rl in rec.get("resourceLogs", []):
            if not _resource_is_codex(rl.get("resource", {})):
                continue
            for sl in rl.get("scopeLogs", []):
                for lr in sl.get("logRecords", []):
                    attrs = _otlp_attrs_to_dict(lr.get("attributes", []))
                    if all(k in attrs for k in REQUIRED_TOKEN_FIELDS):
                        for k in INT_COERCE_FIELDS:
                            if k in attrs and isinstance(attrs[k], str):
                                attrs[k] = int(attrs[k])
                        last_match = attrs

    if last_match is None:
        raise ValueError(f"No Codex usage records (service.name={CODEX_SERVICE_NAME}) found in {path}")

    return {
        "input_tokens": last_match["input_token_count"],
        "output_tokens": last_match["output_token_count"],
        "cached_tokens": last_match["cached_token_count"],
        "reasoning_tokens": last_match.get("reasoning_token_count"),
        "tool_tokens": last_match.get("tool_token_count"),
        "model": last_match.get("model"),
        "_source_file": str(path),
    }
