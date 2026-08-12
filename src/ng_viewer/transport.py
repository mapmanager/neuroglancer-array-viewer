"""Non-blocking state dispatch used by the viewer HTTP transport."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from .models import ViewState

LOGGER = logging.getLogger(__name__)


class ViewStateDispatcher:
    """Deliver only the newest viewer state away from request threads."""

    def __init__(self) -> None:
        """Start a daemon dispatch thread."""
        self.callbacks: set[Callable[[ViewState], None]] = set()
        self.lock = threading.Lock()
        self.pending: queue.Queue[ViewState | None] = queue.Queue(maxsize=1)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def subscribe(self, callback: Callable[[ViewState], None]) -> Callable[[], None]:
        """Register a callback and return an unsubscribe function."""
        if not callable(callback):
            raise TypeError("View-state callback must be callable")
        with self.lock:
            self.callbacks.add(callback)
        return lambda: self._discard(callback)

    def _discard(self, callback: Callable[[ViewState], None]) -> None:
        with self.lock:
            self.callbacks.discard(callback)

    def publish(self, state: ViewState) -> None:
        """Queue the newest state, replacing one pending older state."""
        try:
            self.pending.put_nowait(state)
        except queue.Full:
            self.pending.get_nowait()
            self.pending.put_nowait(state)

    def close(self) -> None:
        """Stop the dispatcher after any running callback returns."""
        try:
            self.pending.put_nowait(None)
        except queue.Full:
            self.pending.get_nowait()
            self.pending.put_nowait(None)
        self.thread.join(timeout=1)

    def _run(self) -> None:
        while (state := self.pending.get()) is not None:
            with self.lock:
                callbacks = tuple(self.callbacks)
            for callback in callbacks:
                try:
                    callback(state)
                except Exception:
                    LOGGER.exception("View-state callback failed")
