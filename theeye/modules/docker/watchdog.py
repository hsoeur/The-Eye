"""Watchdog du moteur Docker : sonde légère, machine à états et garde-fous de relance (sans I/O système).

États : healthy -> degraded -> hung -> recovering -> healthy. La logique est pure (horloge injectable) pour être
testée sans Docker ; l'exécution des commandes et les effets de bord vivent dans __init__.py, incident.py, recovery.py.
"""
import os
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ...core.process import NOT_FOUND, TIMEOUT, Result

HEALTHY, DEGRADED, HUNG, RECOVERING = "healthy", "degraded", "hung", "recovering"
STATE_CODES = {HEALTHY: 0, DEGRADED: 1, HUNG: 2, RECOVERING: 3}
OK, SLOW, FAIL = "ok", "slow", "fail"
PROBE_CMD = ["docker", "version", "--format", "{{.Server.Version}}"]
LIST_CMD = ["docker", "ps", "-q"]
VERSION_RE = re.compile(r"\d+\.\d+")
HISTORY_POINTS = 120
RECOVERY_GRACE_S = 300.0  # après une relance, les échecs de sonde ne comptent pas (Docker redémarre)

# clé: (type, minimum, maximum, défaut)
SPEC: Dict[str, Tuple[type, float, float, Any]] = {
    "interval_s": (float, 5, 3600, 15.0),
    "probe_interval_s": (float, 5, 600, 30.0),
    "probe_timeout_s": (float, 2, 120, 15.0),
    "slow_threshold_s": (float, 0.5, 60, 5.0),
    "degraded_after": (int, 1, 100, 2),
    "hung_after": (int, 1, 100, 3),
    "healthy_after": (int, 1, 100, 3),
    "capture_on_hung": (bool, 0, 1, True),
    "max_incidents": (int, 1, 100, 10),
    "auto_recover": (bool, 0, 1, False),
    "recover_after_s": (float, 0, 3600, 120.0),
    "recover_cooldown_min": (float, 1, 1440, 30.0),
    "max_recoveries_per_day": (int, 0, 24, 3),
}


@dataclass(frozen=True)
class WatchdogConfig:
    interval_s: float = 15.0
    probe_interval_s: float = 30.0
    probe_timeout_s: float = 15.0
    slow_threshold_s: float = 5.0
    degraded_after: int = 2
    hung_after: int = 3
    healthy_after: int = 3
    capture_on_hung: bool = True
    max_incidents: int = 10
    auto_recover: bool = False
    recover_after_s: float = 120.0
    recover_cooldown_min: float = 30.0
    max_recoveries_per_day: int = 3
    ignored: Tuple[str, ...] = field(default=(), compare=False)

    @classmethod
    def from_dict(cls, raw: Optional[Mapping[str, Any]]) -> "WatchdogConfig":
        """Valide les bornes ; une valeur invalide est ignorée (défaut conservé) et listée dans `ignored`."""
        values: Dict[str, Any] = {}
        ignored: List[str] = []
        for key, (kind, lo, hi, _) in SPEC.items():
            if not raw or key not in raw:
                continue
            v = raw[key]
            if kind is bool:
                ok = isinstance(v, bool)
            else:
                ok = isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
                if ok and kind is int:
                    ok = float(v).is_integer()
            if ok:
                values[key] = bool(v) if kind is bool else kind(v)
            else:
                ignored.append(key)
        timeout = values.get("probe_timeout_s", SPEC["probe_timeout_s"][3])
        if values.get("slow_threshold_s", SPEC["slow_threshold_s"][3]) > timeout:
            values["slow_threshold_s"] = timeout
        return cls(**values, ignored=tuple(ignored))

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ignored"] = list(self.ignored)
        return d


def classify(r: Result, latency: float, cfg: WatchdogConfig) -> Tuple[str, str]:
    """Résultat de `docker version` -> (ok | slow | fail, détail)."""
    if r.code == TIMEOUT:
        return FAIL, f"délai dépassé ({cfg.probe_timeout_s:.0f} s)"
    if r.code == NOT_FOUND:
        return FAIL, "CLI docker introuvable"
    if r.code != 0:
        return FAIL, " ".join((r.err or r.out).split())[:200] or f"code {r.code}"
    version = r.out.strip()
    if not VERSION_RE.match(version):
        return FAIL, "réponse inattendue : " + version[:80]
    return (SLOW if latency > cfg.slow_threshold_s else OK), version


def classify_listing(r: Result, cfg: WatchdogConfig) -> Optional[str]:
    """Résultat de `docker ps -q` (sonde profonde) -> None si correct, sinon le motif de l'échec."""
    if r.code == TIMEOUT:
        return f"docker ps : délai dépassé ({cfg.probe_timeout_s:.0f} s)"
    if r.code != 0:
        return "docker ps : " + (" ".join((r.err or r.out).split())[:160] or f"code {r.code}")
    return None


def docker_is_local(environ: Optional[Mapping[str, str]] = None, os_name: Optional[str] = None) -> Tuple[bool, str]:
    """La relance automatique n'a de sens que si Docker Desktop tourne sur l'hôte de The Eye."""
    environ = os.environ if environ is None else environ
    if (os_name or os.name) != "nt":
        return False, "relance automatique réservée à Windows"
    host = (environ.get("DOCKER_HOST") or "").strip()
    if host and not host.lower().startswith(("npipe:", "unix:")):
        return False, f"Docker distant (DOCKER_HOST={host[:60]})"
    return True, ""


class Watchdog:
    """Machine à états du moteur. Un seul événement par changement d'état ; un incident = hung jusqu'à healthy."""

    def __init__(self, cfg: WatchdogConfig, clock: Callable[[], float] = time.time,
                 emit: Optional[Callable[..., None]] = None):
        self.cfg, self._clock, self._emit = cfg, clock, emit or (lambda *a, **k: None)
        self._lock = threading.RLock()
        self.state = HEALTHY
        self.since = clock()
        self.history: "deque[List[Any]]" = deque(maxlen=HISTORY_POINTS)
        self.last: Optional[Dict[str, Any]] = None
        self.last_ok_version = ""
        self.cli_missing = False
        self.fails = self.bad = self.oks = 0
        self.hung_since: Optional[float] = None
        self.grace_until = 0.0
        self.incident_open = False
        self.capture_pending = False
        self.capture_finished = False

    # --- entrées --------------------------------------------------------------------------------------------------
    def record(self, kind: str, latency: float, detail: str = "", code: Optional[int] = None) -> Optional[str]:
        """Intègre une mesure de sonde ; renvoie le nouvel état s'il a changé."""
        with self._lock:
            now = self._clock()
            if kind == OK:
                self.oks, self.bad, self.fails = self.oks + 1, 0, 0
                self.last_ok_version = detail
            else:
                self.oks, self.bad = 0, self.bad + 1
                self.fails = self.fails + 1 if kind == FAIL else 0
            self.cli_missing = code == NOT_FOUND
            changed = None
            for _ in range(2):
                target = self._target(now)
                if target == self.state:
                    break
                self._enter(target, now, latency, detail)
                changed = target
            self.last = {"t": now, "kind": kind, "latency_s": round(latency, 3), "detail": detail, "state": self.state}
            self.history.append([round(now), round(latency, 3), kind, self.state])
            return changed

    def _target(self, now: float) -> str:
        c, s = self.cfg, self.state
        if s == HUNG:
            return RECOVERING if self.oks >= 1 else HUNG
        if self.fails >= c.hung_after and not (s == RECOVERING and now < self.grace_until):
            return HUNG
        if s == HEALTHY:
            return DEGRADED if self.bad >= c.degraded_after else HEALTHY
        return HEALTHY if self.oks >= c.healthy_after else s

    def _enter(self, new: str, now: float, latency: float, detail: str) -> None:
        prev, self.state, self.since = self.state, new, now
        data = {"state": new, "latency_s": round(latency, 3), "detail": detail}
        if new == DEGRADED:
            self._emit("docker_engine_degraded", f"Moteur Docker dégradé ({detail})", "warning", **data)
        elif new == HUNG:
            self.hung_since = self.hung_since or now
            if not self.incident_open:
                self.incident_open = True
                self.capture_pending = self.cfg.capture_on_hung
                self.capture_finished = False
            self._emit("docker_engine_hung", f"Moteur Docker figé ({detail})", "critical", **data)
        elif new == HEALTHY:
            self.hung_since, self.grace_until = None, 0.0
            self.incident_open = self.capture_pending = False
            if prev != HEALTHY:
                self._emit("docker_engine_recovered", "Moteur Docker rétabli", "ok", **data)

    # --- incident et relance --------------------------------------------------------------------------------------
    def take_capture(self) -> bool:
        """Vrai une seule fois par incident : l'appelant doit alors lancer la capture des preuves."""
        with self._lock:
            pending, self.capture_pending = self.capture_pending, False
            return pending

    def mark_capture_finished(self) -> None:
        with self._lock:
            self.capture_finished = True

    def retry_capture(self) -> None:
        """Capture non réalisée (autre opération en cours) : la redemander à la prochaine sonde."""
        with self._lock:
            if self.incident_open and not self.capture_finished:
                self.capture_pending = self.cfg.capture_on_hung

    def begin_recovery(self) -> None:
        with self._lock:
            now = self._clock()
            self.state, self.since, self.grace_until = RECOVERING, now, now + RECOVERY_GRACE_S
            self.fails = self.bad = self.oks = 0

    def abort_recovery(self) -> None:
        with self._lock:
            self.state, self.since, self.grace_until = HUNG, self._clock(), 0.0

    def hung_for(self) -> float:
        with self._lock:
            return self._clock() - self.hung_since if self.hung_since else 0.0

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"state": self.state, "state_code": STATE_CODES[self.state], "since": self.since,
                    "last": self.last, "history": list(self.history), "hung_since": self.hung_since,
                    "incident_open": self.incident_open, "capture_finished": self.capture_finished}

    def latency(self) -> Optional[float]:
        with self._lock:
            return self.last["latency_s"] if self.last else None


class RecoveryGuard:
    """Garde-fous de la relance automatique : délai minimal entre deux relances et plafond sur 24 h glissantes."""

    def __init__(self, cfg: WatchdogConfig, clock: Callable[[], float] = time.time,
                 history: Optional[List[float]] = None):
        self.cfg, self._clock = cfg, clock
        self.history: List[float] = sorted(float(t) for t in (history or []) if isinstance(t, (int, float)))

    def _recent(self, now: float) -> List[float]:
        return [t for t in self.history if now - t < 86400]

    def allow(self) -> Tuple[bool, str]:
        now = self._clock()
        if self.history and now - self.history[-1] < self.cfg.recover_cooldown_min * 60:
            return False, f"délai minimal entre deux relances ({self.cfg.recover_cooldown_min:.0f} min)"
        if len(self._recent(now)) >= self.cfg.max_recoveries_per_day:
            return False, f"plafond de {self.cfg.max_recoveries_per_day} relance(s) par 24 h atteint"
        return True, ""

    def record(self) -> None:
        now = self._clock()
        self.history = [*self._recent(now), now]

    def summary(self) -> Dict[str, Any]:
        now = self._clock()
        last = self.history[-1] if self.history else 0.0
        return {"last": last, "last_24h": len(self._recent(now)), "max_per_day": self.cfg.max_recoveries_per_day,
                "cooldown_until": last + self.cfg.recover_cooldown_min * 60 if last else 0.0}
