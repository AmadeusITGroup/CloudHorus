"""Generic heartbeat for long-running operations.

Emits periodic INFO-level log messages when the logger has been silent
for more than ``interval`` seconds.  Completely transparent — no changes
needed to existing logging call-sites.

The context manager installs a lightweight logging.Filter that records
the wall-clock time of the last log emission.  A daemon thread wakes
every ``interval`` seconds and, if the logger has been quiet for at
least that long, emits a ``[HEARTBEAT]`` INFO message.  This keeps
pipe-based readers (WebUI, CI) alive during CPU-heavy or API-heavy
phases that would otherwise produce no output.

Usage::

    from utils.heartbeat import Heartbeat

    with Heartbeat(logger, "Resource graph generation", interval=5):
        # ... long-running code with intermittent logging ...
        # Heartbeats fire automatically only during silent gaps.
"""

import logging
import threading
import time
from typing import Optional


class _ActivityTracker(logging.Filter):
    """Transparent filter that records the timestamp of each log emission."""

    def __init__(self) -> None:
        super().__init__()
        self.last_activity: float = time.time()

    def filter(self, record: logging.LogRecord) -> bool:
        self.last_activity = time.time()
        return True  # never suppress — purely observational


class Heartbeat:
    """Context manager — emits keepalive logs during silent periods.

    :param logger:   Logger instance to monitor and emit heartbeats on.
    :param phase:    Human-readable label for the current phase.
    :param interval: Minimum seconds of silence before a heartbeat fires.
    """

    def __init__(
        self,
        logger: logging.Logger,
        phase: str = "Processing",
        interval: float = 5.0,
    ) -> None:
        self._logger = logger
        self._phase = phase
        self._interval = interval
        self._tracker = _ActivityTracker()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start: float = 0.0

    # --- context manager protocol ----------------------------------------

    def __enter__(self) -> "Heartbeat":
        self._start = time.time()
        self._tracker.last_activity = self._start
        self._logger.addFilter(self._tracker)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._logger.removeFilter(self._tracker)
        if self._thread:
            self._thread.join(timeout=2)

    # --- public helpers ---------------------------------------------------

    def update_phase(self, new_phase: str) -> None:
        """Change the phase label mid-run (e.g. when entering a new stage)."""
        self._phase = new_phase

    # --- internal ---------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            silence = time.time() - self._tracker.last_activity
            if silence >= self._interval:
                elapsed = time.time() - self._start
                self._logger.debug(f"[HEARTBEAT] {self._phase}... still working " f"({elapsed:.0f}s elapsed)")
