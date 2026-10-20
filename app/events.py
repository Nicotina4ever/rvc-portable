"""Bus di eventi in-process per SSE (log, job, monitor, config, engine).

Semplice pub/sub thread-safe con storico circolare, cosi' il frontend puo'
riconnettersi e ricevere gli eventi persi (``Last-Event-ID`` / ``since``).
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


class Subscription:
    """Coda di eventi per un singolo client SSE."""

    def __init__(self, bus: "EventBus", maxsize: int = 1000):
        self._bus = bus
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=maxsize)
        self.closed = False

    def put(self, event: Dict[str, Any]) -> None:
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                pass

    def get(self, timeout: float) -> Optional[Dict[str, Any]]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self.closed = True
        self._bus._remove(self)  # noqa: SLF001 - stesso package


class EventBus:
    """Fan-out thread-safe con storico limitato."""

    def __init__(self, history: int = 500):
        self._lock = threading.Lock()
        self._subscribers: List[Subscription] = []
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history)
        self._seq = 0

    # ------------------------------------------------------------------ pub
    def publish(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "id": self._seq,
                "type": event_type,
                "ts": round(time.time(), 3),
                "data": data or {},
            }
            self._history.append(event)
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)
        return event

    # ------------------------------------------------------------------ sub
    def subscribe(self) -> Subscription:
        subscription = Subscription(self)
        with self._lock:
            self._subscribers.append(subscription)
        return subscription

    def _remove(self, subscription: Subscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    # -------------------------------------------------------------- history
    def replay_since(self, last_id: Optional[int]) -> List[Dict[str, Any]]:
        with self._lock:
            if not last_id:
                return []
            return [event for event in self._history if event["id"] > last_id]

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._seq

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


BUS = EventBus()


def publish(event_type: str, **data: Any) -> Dict[str, Any]:
    """Scorciatoia usata dai moduli applicativi."""
    return BUS.publish(event_type, data)
