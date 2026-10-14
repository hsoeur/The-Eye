"""Persistance JSON atomique (écriture temporaire + remplacement)."""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("eye.storage")


class JsonStore:
    def __init__(self, path: Path, default: Callable[[], Any] = dict):
        self.path = Path(path)
        self._default = default
        self._lock = threading.Lock()

    def load(self) -> Any:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._default()
        except (OSError, ValueError) as e:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            log.error("%s illisible (%s), copie conservée dans %s", self.path.name, e, backup.name)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return self._default()

    def save(self, data: Any) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
