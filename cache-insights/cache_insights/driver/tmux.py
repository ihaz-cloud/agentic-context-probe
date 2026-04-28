"""tmux-based driver for interactive vendor CLIs.

The vendor CLIs (Claude Code, Codex, Gemini) are interactive-only — they
have no batch / stdin mode for the workflows we need. This driver wraps tmux
for session lifecycle and uses load-buffer + paste-buffer for prompt delivery.
send-keys is reserved for non-text actions (Enter, Escape, slash commands).

Completion is detected by polling the vendor's local attribution source
(reusing the cws.3/4/5 parsers as the predicate), not by parsing terminal
output. Terminal output parsing is fragile under ANSI/TUI redraws.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from cache_insights.driver.dispatch import LaunchSpec, get_launch_spec


DEFAULT_POLL_INTERVAL_S = 0.25
DEFAULT_TIMEOUT_S = 60.0


class TmuxError(RuntimeError):
    pass


class CompletionTimeout(TmuxError):
    pass


def _tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["tmux", *args], check=check, capture_output=True, text=True)


class TmuxSession:
    """A named tmux session running one vendor CLI."""

    def __init__(self, name: str, spec: LaunchSpec, working_dir: Path | None = None):
        self.name = name
        self.spec = spec
        self.working_dir = working_dir or Path.cwd()
        self._launched = False

    # ---- session lifecycle ---------------------------------------------

    def exists(self) -> bool:
        result = _tmux("has-session", "-t", self.name, check=False)
        return result.returncode == 0

    def launch(self, *extra_args: str) -> None:
        """Start the vendor CLI inside a fresh detached tmux session.

        Raises TmuxError if a session with this name already exists.
        """
        if self.exists():
            raise TmuxError(f"tmux session {self.name!r} already exists")
        cmd = [self.spec.binary, *self.spec.default_args, *extra_args]
        _tmux(
            "new-session",
            "-d",
            "-s",
            self.name,
            "-c",
            str(self.working_dir),
            *cmd,
        )
        self._launched = True

    def teardown(self) -> None:
        if self.exists():
            _tmux("kill-session", "-t", self.name, check=False)
        self._launched = False

    # ---- prompt delivery -----------------------------------------------

    def send_prompt(self, text: str) -> None:
        """Deliver a prompt via load-buffer + paste-buffer + Enter.

        load-buffer reads from a file on disk (avoiding shell-escape pitfalls).
        paste-buffer types the buffer into the focused pane (NOT send-keys for
        text — Gemini CLI ignores send-keys Enter for paste-buffer-style flows).
        Enter is sent separately as a non-text action.
        """
        if not self.exists():
            raise TmuxError(f"tmux session {self.name!r} is not running")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(text)
            tmp_path = f.name
        try:
            _tmux("load-buffer", tmp_path)
            _tmux("paste-buffer", "-t", self.name)
            _tmux("send-keys", "-t", self.name, "Enter")
        finally:
            os.unlink(tmp_path)

    def send_keys(self, *keys: str) -> None:
        """Send raw key actions (Escape, Enter, slash commands).

        Reserved for non-text inputs. For prompt text use send_prompt().
        """
        if not self.exists():
            raise TmuxError(f"tmux session {self.name!r} is not running")
        _tmux("send-keys", "-t", self.name, *keys)

    # ---- completion polling --------------------------------------------

    def wait_for_completion(
        self,
        baseline_mtime: float | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        poll_interval: float = DEFAULT_POLL_INTERVAL_S,
        session_uuid: str | None = None,
    ) -> Path:
        """Poll the vendor's attribution file until the parser succeeds.

        Args:
            baseline_mtime: file mtime at the moment send_prompt() was called.
                Used to ensure we wait for a NEW write, not a stale one. If None,
                we accept the current state as completion (useful only for
                first-launch verification).
            timeout: seconds before raising CompletionTimeout.
            poll_interval: seconds between polls.
            session_uuid: forwarded to the completion_source factory (Claude only).

        Returns:
            The path that satisfied the predicate.
        """
        deadline = time.monotonic() + timeout
        path = self.spec.completion_source(session_uuid=session_uuid)
        while time.monotonic() < deadline:
            if path.exists():
                if baseline_mtime is None or path.stat().st_mtime > baseline_mtime:
                    if self.spec.completion_check(path):
                        return path
            time.sleep(poll_interval)
            # The source path may change for vendors with rotating files
            path = self.spec.completion_source(session_uuid=session_uuid)
        raise CompletionTimeout(
            f"completion not detected on {path} within {timeout}s for {self.spec.vendor}"
        )

    def baseline_mtime(self, session_uuid: str | None = None) -> float | None:
        """Snapshot the completion-source mtime BEFORE sending a prompt.

        Returns None if the file does not yet exist.
        """
        path = self.spec.completion_source(session_uuid=session_uuid)
        if not path.exists():
            return None
        return path.stat().st_mtime


# ---- convenience entrypoint --------------------------------------------


@contextmanager
def driver(
    vendor: str,
    *,
    name: str | None = None,
    working_dir: Path | None = None,
    extra_launch_args: tuple[str, ...] = (),
):
    """Context manager: launch a vendor CLI, yield the session, tear down on exit."""
    spec = get_launch_spec(vendor)
    session_name = name or f"cache-insights-{vendor}-{os.getpid()}"
    session = TmuxSession(session_name, spec, working_dir)
    session.launch(*extra_launch_args)
    try:
        yield session
    finally:
        session.teardown()
