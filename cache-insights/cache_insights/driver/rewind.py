"""Vendor-agnostic rewind helper.

§4.2 rewind primitive validation (cache-insights-0to.8) uses this helper to
send the vendor-specific keystroke sequence that returns the conversation
state to a prior turn — without launching a new tmux session (rewind is
in-place, unlike fork).

Per-vendor mechanics (per ``dispatch.py:LaunchSpec.rewind_keys``):

- **anthropic**: ``Escape Escape`` opens the rewind menu; ``Enter Enter``
  selects the most-recent rewind point and confirms.
- **openai**: not supported (``rewind_keys=None`` in ``LaunchSpec``).
- **google**: not supported (``rewind_keys=None`` in ``LaunchSpec``).

Vendors without registered ``rewind_keys`` raise ``RewindNotSupported``,
which callers translate into ``verdict="skipped"``.

Future extension: if lexicon study reveals codex / gemini rewind sequences,
populate ``rewind_keys`` in ``dispatch.py`` and this helper picks them up
without API changes.
"""

from __future__ import annotations

import time

from cache_insights.driver.dispatch import get_launch_spec
from cache_insights.driver.tmux import TmuxSession


class RewindError(RuntimeError):
    """Raised when a rewind primitive cannot be executed.

    Callers (§4.2 test driver) translate this into ``verdict=error``.
    """


class RewindNotSupported(RewindError):
    """Raised when the vendor does not have a registered rewind primitive.

    Callers translate this into ``verdict="skipped"`` (a non-fatal outcome —
    the test result is recorded with `requests` partial and `notes` citing
    the skip reason).
    """


def rewind_session(
    session: TmuxSession,
    vendor: str,
    *,
    depth: int = 1,
) -> None:
    """Rewind the conversation state of a vendor CLI session.

    Args:
        session: the live ``TmuxSession`` to rewind in place.
        vendor: one of ``openai|anthropic|google``.
        depth: number of turns to rewind. Currently only ``depth=1`` is
            tested; values >1 are passed through but vendor support is
            uncharacterized.

    Returns:
        None. Rewind is a side effect on the existing session.

    Raises:
        RewindNotSupported: vendor has no registered rewind primitive.
        RewindError: rewind keys are configured but the keystroke send failed.
        ValueError: vendor is unknown (programming error).
    """
    spec = get_launch_spec(vendor)
    if spec.rewind_keys is None:
        raise RewindNotSupported(
            f"vendor {vendor!r} has no registered rewind primitive "
            "(rewind_keys is None in LaunchSpec)"
        )

    try:
        # Open the rewind menu.
        session.send_keys(*spec.rewind_keys)
        time.sleep(0.5)
        # Navigate to the target depth (most-recent for depth=1).
        # depth-1 down arrows; for depth==1 we stay on the most-recent option.
        for _ in range(max(0, depth - 1)):
            session.send_keys("Down")
            time.sleep(0.1)
        # Confirm: Enter selects the rewind point, second Enter confirms.
        session.send_keys("Enter")
        time.sleep(0.3)
        session.send_keys("Enter")
        time.sleep(0.3)
    except RewindError:
        raise
    except Exception as e:  # noqa: BLE001 — wrap arbitrary tmux errors
        raise RewindError(f"{type(e).__name__}: {e}") from e


__all__ = ["rewind_session", "RewindError", "RewindNotSupported"]
