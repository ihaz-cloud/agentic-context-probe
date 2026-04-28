"""Read API keys and other secrets from prd/config.env without polluting os.environ."""

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ENV = PROJECT_ROOT / "prd" / "config.env"


@lru_cache(maxsize=64)
def load_env_var(name: str) -> str:
    """Read a variable from prd/config.env via bash, falling back to os.environ.

    Returns empty string if the variable is unset or empty in both sources.
    Cached to avoid repeated subprocess invocations during a run.
    """
    val = os.environ.get(name, "").strip()
    if val:
        return val
    if not CONFIG_ENV.exists():
        return ""
    try:
        proc = subprocess.run(
            [
                "bash",
                "-c",
                f"set -a; source '{CONFIG_ENV}'; "
                f'printf "%s" "${{{name}:-}}"',
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except subprocess.CalledProcessError:
        return ""
