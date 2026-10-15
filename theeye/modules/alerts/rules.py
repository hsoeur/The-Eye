"""Règles d'alerte et fenêtres de maintenance : modèle, validation et correspondance (sans I/O)."""
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timedelta
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional

OPERATORS = {
    ">": lambda v, t: v > t, ">=": lambda v, t: v >= t,
    "<": lambda v, t: v < t, "<=": lambda v, t: v <= t,
    "==": lambda v, t: v == t, "!=": lambda v, t: v != t,
}
SEVERITIES = ("info", "warning", "critical")
SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
METRIC_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
ID_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")
MAX_SECONDS = 7 * 86400


def _num(body: Dict[str, Any], key: str, default: Optional[float] = None, lo: float = 0, hi: float = 1e12) -> Optional[float]:
    raw = body.get(key, default)
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} doit être un nombre")
    if not lo <= value <= hi:
        raise ValueError(f"{key} hors limites")
    return value


def _str_list(raw: Any, default: List[str]) -> List[str]:
    if raw is None:
        return list(default)
    if not isinstance(raw, list):
        raise ValueError("liste attendue")
    return [str(x).strip()[:128] for x in raw if str(x).strip()][:200]


@dataclass
class Rule:
    id: str
    name: str
    metric: str
    operator: str
    threshold: float
    severity: str = "warning"
    critical_threshold: Optional[float] = None
    for_seconds: float = 0
    recover_seconds: float = 60
    hysteresis: float = 0
    source: str = ""
    targets: List[str] = field(default_factory=lambda: ["*"])
    exclude: List[str] = field(default_factory=list)
    item: str = ""
    enabled: bool = True
    description: str = ""

    @classmethod
    def from_dict(cls, body: Dict[str, Any], rule_id: Optional[str] = None) -> "Rule":
        name = str(body.get("name", "")).strip()[:120]
        if not name:
            raise ValueError("nom requis")
        metric = str(body.get("metric", "")).strip()
        if not METRIC_RE.fullmatch(metric):
            raise ValueError("métrique invalide")
        operator = str(body.get("operator", ""))
        if operator not in OPERATORS:
            raise ValueError("opérateur invalide")
        severity = str(body.get("severity", "warning"))
        if severity not in SEVERITIES:
            raise ValueError("sévérité invalide")
        threshold = _num(body, "threshold", lo=-1e12)
        if threshold is None:
            raise ValueError("seuil requis")
        critical = _num(body, "critical_threshold", lo=-1e12)
        if critical is not None and operator in (">", ">=") and critical < threshold:
            raise ValueError("le seuil critique doit être supérieur au seuil")
        if critical is not None and operator in ("<", "<=") and critical > threshold:
            raise ValueError("le seuil critique doit être inférieur au seuil")
        rid = rule_id or str(body.get("id") or "") or "r-" + uuid.uuid4().hex[:8]
        if not ID_RE.fullmatch(rid):
            raise ValueError("identifiant invalide")
        return cls(
            id=rid, name=name, metric=metric, operator=operator, threshold=threshold, severity=severity,
            critical_threshold=critical, for_seconds=_num(body, "for_seconds", 0, hi=MAX_SECONDS) or 0,
            recover_seconds=_num(body, "recover_seconds", 60, hi=MAX_SECONDS) or 0,
            hysteresis=_num(body, "hysteresis", 0) or 0, source=str(body.get("source", "") or "")[:32],
            targets=_str_list(body.get("targets"), ["*"]) or ["*"], exclude=_str_list(body.get("exclude"), []),
            item=str(body.get("item", "") or "")[:128], enabled=bool(body.get("enabled", True)),
            description=str(body.get("description", "") or "")[:500])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def matches(self, obs: Dict[str, Any]) -> bool:
        if not self.enabled or obs.get("metric") != self.metric:
            return False
        if self.source and obs.get("source") != self.source:
            return False
        target = obs.get("target", "")
        if "*" not in self.targets and target not in self.targets:
            return False
        if target in self.exclude:
            return False
        return not self.item or fnmatchcase(str(obs.get("item", "")).lower(), self.item.lower())

    def level(self, value: float) -> Optional[str]:
        """Sévérité atteinte par la valeur, ou None si aucun seuil n'est franchi."""
        compare = OPERATORS[self.operator]
        if self.critical_threshold is not None and compare(value, self.critical_threshold):
            return "critical"
        if compare(value, self.threshold):
            return self.severity
        return None

    def cleared(self, value: float) -> bool:
        """Vrai si la valeur est revenue franchement sous le seuil (hystérésis comprise)."""
        if self.level(value) is not None:
            return False
        h = self.hysteresis
        if not h:
            return True
        if self.operator in (">", ">="):
            return value <= self.threshold - h
        if self.operator in ("<", "<="):
            return value >= self.threshold + h
        return True


def docker_watchdog_rules() -> List[Rule]:
    return [
        Rule(id="docker-engine-slow", name="Moteur Docker lent", metric="docker_engine_latency_s", operator=">",
             threshold=5, severity="warning", for_seconds=60, recover_seconds=60, source="docker",
             description="La sonde de santé du moteur Docker répond lentement."),
        Rule(id="docker-engine-hung", name="Moteur Docker figé", metric="docker_engine_hung", operator=">=",
             threshold=1, severity="critical", for_seconds=0, recover_seconds=60, source="docker",
             description="Le moteur Docker ne répond plus (preuves capturées dans data/incidents)."),
    ]


def default_rules(docker_active: bool = False) -> List[Rule]:
    """Règles par défaut ; `docker-down` n'est actif d'emblée que si le module docker l'est."""
    return [
        Rule(id="host-down", name="Machine injoignable", metric="reachable", operator="<", threshold=1,
             severity="critical", for_seconds=120, recover_seconds=60,
             description="La machine ne répond plus à la collecte."),
        Rule(id="cpu-high", name="CPU élevé", metric="cpu_pct", operator=">", threshold=90, severity="warning",
             for_seconds=300, recover_seconds=120, hysteresis=5),
        Rule(id="mem-high", name="Mémoire élevée", metric="mem_pct", operator=">", threshold=90, severity="warning",
             for_seconds=300, recover_seconds=120, hysteresis=3),
        Rule(id="disk-low", name="Espace disque faible", metric="disk_free_pct", operator="<", threshold=15,
             critical_threshold=5, severity="warning", for_seconds=300, recover_seconds=300, hysteresis=2),
        Rule(id="service-fault", name="Service en défaut", metric="service_fault", operator=">=", threshold=1,
             severity="critical", for_seconds=60, recover_seconds=30,
             description="Service automatique arrêté ou en échec."),
        Rule(id="container-fault", name="Container en défaut", metric="container_fault", operator=">=", threshold=1,
             severity="critical", for_seconds=30, recover_seconds=30),
        Rule(id="docker-down", name="Docker indisponible", metric="docker_available", operator="<", threshold=1,
             severity="critical", for_seconds=60,              recover_seconds=60, enabled=docker_active,
                          description="Actif par défaut si le module docker est actif sur cette installation."),
        Rule(id="device-offline", name="Équipement réseau hors ligne", metric="device_online", operator="<",
             threshold=1, severity="warning", for_seconds=180, recover_seconds=60,
             description="Équipements nommés dans la cartographie."),
                     *docker_watchdog_rules(),
                 ]


@dataclass
class Maintenance:
    id: str
    name: str
    targets: List[str] = field(default_factory=lambda: ["*"])
    kind: str = "once"  # once | daily | weekly
    starts_at: float = 0.0
    ends_at: float = 0.0
    days: List[int] = field(default_factory=list)  # lundi = 0 (kind weekly)
    start_time: str = "00:00"
    duration_min: int = 60
    comment: str = ""
    enabled: bool = True
    created_by: str = ""

    @classmethod
    def from_dict(cls, body: Dict[str, Any], mid: Optional[str] = None, author: str = "") -> "Maintenance":
        name = str(body.get("name", "")).strip()[:120]
        if not name:
            raise ValueError("nom requis")
        kind = str(body.get("kind", "once"))
        if kind not in ("once", "daily", "weekly"):
            raise ValueError("type de fenêtre invalide")
        m = cls(id=mid or "m-" + uuid.uuid4().hex[:8], name=name, targets=_str_list(body.get("targets"), ["*"]) or ["*"],
                kind=kind, comment=str(body.get("comment", "") or "")[:500], enabled=bool(body.get("enabled", True)),
                created_by=author[:80])
        if kind == "once":
            m.starts_at, m.ends_at = float(_num(body, "starts_at", hi=4e9) or 0), float(_num(body, "ends_at", hi=4e9) or 0)
            if m.ends_at <= m.starts_at:
                raise ValueError("la fin doit suivre le début")
        else:
            start = str(body.get("start_time", "00:00"))
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", start):
                raise ValueError("heure de début invalide (HH:MM)")
            m.start_time = start
            m.duration_min = int(_num(body, "duration_min", 60, lo=1, hi=1440) or 60)
            days = body.get("days") or []
            if kind == "weekly":
                if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
                    raise ValueError("jours invalides (0 = lundi ... 6 = dimanche)")
                m.days = sorted(set(days))
        return m

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def covers(self, target: str) -> bool:
        return "*" in self.targets or target in self.targets

    def active_at(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.kind == "once":
            return self.starts_at <= now < self.ends_at
        current = datetime.fromtimestamp(now)
        hh, mm = (int(x) for x in self.start_time.split(":"))
        for back in (0, 1):
            day = (current - timedelta(days=back)).date()
            if self.kind == "weekly" and day.weekday() not in self.days:
                continue
            start = datetime.combine(day, dtime(hh, mm))
            if start <= current < start + timedelta(minutes=self.duration_min):
                return True
        return False
