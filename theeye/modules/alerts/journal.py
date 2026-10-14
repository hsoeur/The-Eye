"""Journal d'écriture différée : les opérations sont rejouées sur la base, dans l'ordre, jusqu'au succès.

L'évaluation des alertes ne dépend jamais de la disponibilité de MySQL : si la base tombe, les opérations
s'accumulent dans un fichier local (data/alerts_outbox.jsonl) et sont appliquées à la reconnexion, même après
un redémarrage de The Eye.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import SqlStore, StoreError, StoreUnavailable

log = logging.getLogger("eye.alerts.journal")
MAX_PENDING = 200_000


class Journal:
    def __init__(self, store: SqlStore, path: Path):
        self.store, self.path = store, Path(path)
        self._lock = threading.RLock()
        self._ops: List[Dict[str, Any]] = []
        self.last_error = ""
        self.last_ok = 0.0
        self.dropped = 0
        self.available = False
        self._load()

    def _load(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        except OSError as e:
            log.error("journal illisible (%s)", e)
            return
        for line in lines:
            try:
                self._ops.append(json.loads(line))
            except ValueError:
                self.dropped += 1

    def pending(self) -> int:
        with self._lock:
            return len(self._ops)

    def push(self, ops: List[Dict[str, Any]]) -> None:
        if not ops:
            return
        stamped = [{**op, "t": op.get("t", time.time())} for op in ops]
        with self._lock:
            self._ops.extend(stamped)
            if len(self._ops) > MAX_PENDING:
                excess = len(self._ops) - MAX_PENDING
                del self._ops[:excess]
                self.dropped += excess
                self._rewrite()
            else:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as fh:
                        fh.write("".join(json.dumps(op, ensure_ascii=False) + "\n" for op in stamped))
                except OSError:
                    log.exception("écriture du journal impossible")

    def _rewrite(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text("".join(json.dumps(op, ensure_ascii=False) + "\n" for op in self._ops), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            log.exception("réécriture du journal impossible")

    def flush(self, limit: Optional[int] = None) -> bool:
        """Applique les opérations en attente ; retourne True si la base est joignable et le journal vidé."""
        with self._lock:
            done = 0
            try:
                while self._ops and (limit is None or done < limit):
                    op = self._ops[0]
                    try:
                        self.store.apply(op)
                    except StoreError as e:
                        self.dropped += 1
                        log.error("opération rejetée par la base (%s) : %s", op.get("op"), e)
                    del self._ops[0]
                    done += 1
                if not self._ops:
                    self.store.ping()
                self.available, self.last_error, self.last_ok = True, "", time.time()
                return not self._ops
            except StoreUnavailable as e:
                if self.available or not self.last_error:
                    log.warning("base d'alertes indisponible : %s (%d opération(s) en attente)", e, len(self._ops))
                self.available, self.last_error = False, str(e)
                return False
            finally:
                if done:
                    self._rewrite()
