"""Bus d'événements : les modules publient, l'interface et d'autres modules consomment."""
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .storage import JsonStore

log = logging.getLogger("eye.events")

SEVERITIES = ("info", "ok", "warning", "critical")
MAX_EVENTS = 500


class EventBus:
    def __init__(self, store: Optional[JsonStore] = None):
        self._store = store
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[Dict[str, Any]], None]] = []
        self._events: List[Dict[str, Any]] = (store.load() if store else [])[-MAX_EVENTS:]

    def publish(self, source: str, kind: str, message: str, severity: str = "info", **data: Any) -> Dict[str, Any]:
        if severity not in SEVERITIES:
            severity = "info"
        event = {"id": uuid.uuid4().hex[:10], "t": time.time(), "source": source, "kind": kind,
                 "severity": severity, "message": message, "data": data}
        with self._lock:
            self._events = (self._events + [event])[-MAX_EVENTS:]
            snapshot = list(self._events)
            subscribers = list(self._subscribers)
        if self._store:
            try:
                self._store.save(snapshot)
            except OSError:
                log.exception("sauvegarde des événements impossible")
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                log.exception("abonné d'événements en erreur")
        return event

    def subscribe(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def recent(self, limit: int = 50, source: Optional[str] = None, min_severity: Optional[str] = None) -> List[Dict[str, Any]]:
        floor = SEVERITIES.index(min_severity) if min_severity in SEVERITIES else 0
        with self._lock:
            items = [e for e in self._events
                     if (not source or e["source"] == source) and SEVERITIES.index(e["severity"]) >= floor]
        return items[-limit:][::-1]
