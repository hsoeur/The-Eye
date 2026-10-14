"""Moteur d'alertes : machine à états pure (aucune E/S, horloge injectable).

Cycle de vie d'une alerte (identité stable = règle + cible + élément) :
  condition vraie  -> « pending » (en mémoire) -> « firing » après `for_seconds`
  condition fausse -> « resolved » après `recover_seconds` (anti-flapping) ; une rechute rapide rouvre la même alerte.
L'acquittement, la maintenance (« silenced ») et la corrélation (« suppressed_by » = cause racine) sont des
drapeaux de l'alerte active ; chaque changement produit un événement d'historique immuable.
"""
import time
import uuid
from dataclasses import dataclass, field, fields
from typing import Any, Callable, Dict, Iterable, List, Optional

from .rules import SEV_RANK, Maintenance, Rule

ROOT_METRICS = ("reachable",)
SYSTEM = "système"
FLAP_WINDOW = 3600
FLAP_THRESHOLD = 3


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))


@dataclass
class Alert:
    id: str
    fingerprint: str
    rule_id: str
    rule_name: str
    source: str
    target: str
    target_name: str
    item: str
    metric: str
    severity: str
    started_at: float
    value: float
    peak_value: float
    threshold: float
    operator: str
    message: str
    state: str = "firing"
    resolved_at: Optional[float] = None
    resolve_reason: str = ""
    acked: bool = False
    ack_by: str = ""
    ack_comment: str = ""
    ack_at: Optional[float] = None
    ack_until: Optional[float] = None
    ack_ip: str = ""
    silenced: bool = False
    silence_name: str = ""
    suppressed_by: Optional[str] = None
    flaps: int = 0
    notes: int = 0
    reopened: int = 0
    last_seen: float = 0.0
    updated_at: float = 0.0
    clear_since: Optional[float] = None
    unseen_since: Optional[float] = None

    @property
    def needs_attention(self) -> bool:
        return self.state == "firing" and not (self.acked or self.silenced or self.suppressed_by)

    def to_dict(self) -> Dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["needs_attention"] = self.needs_attention
        d["flapping"] = self.flaps >= FLAP_THRESHOLD
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Alert":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Changes:
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.alerts or self.events)


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


class Engine:
    def __init__(self, clock: Callable[[], float] = time.time, stale_seconds: float = 600,
                 reopen_seconds: float = 300):
        self._clock = clock
        self.stale_seconds, self.reopen_seconds = stale_seconds, reopen_seconds
        self.rules: Dict[str, Rule] = {}
        self.maintenance: Dict[str, Maintenance] = {}
        self.active: Dict[str, Alert] = {}
        self.pending: Dict[str, float] = {}
        self.recent: Dict[str, Alert] = {}
        self._flap_times: Dict[str, List[float]] = {}
        self._touched: Dict[str, Alert] = {}
        self._events: List[Dict[str, Any]] = []

    # --- configuration -------------------------------------------------------------------------------------------
    def set_rules(self, rules: Iterable[Rule]) -> None:
        self.rules = {r.id: r for r in rules}

    def set_maintenance(self, windows: Iterable[Maintenance]) -> None:
        self.maintenance = {m.id: m for m in windows}

    def adopt(self, alerts: Iterable[Alert]) -> None:
        """Reprend des alertes actives connues (base ou instantané) sans écraser celles déjà suivies."""
        for a in alerts:
            if a.state == "firing" and a.fingerprint not in self.active:
                a.clear_since = a.unseen_since = None
                self.active[a.fingerprint] = a

    # --- évaluation ----------------------------------------------------------------------------------------------
    def evaluate(self, observations: List[Dict[str, Any]], now: Optional[float] = None) -> Changes:
        now = self._clock() if now is None else now
        self._begin()
        seen = set()
        for rule in self.rules.values():
            if not rule.enabled:
                continue
            for obs in observations:
                if not rule.matches(obs):
                    continue
                try:
                    value = float(obs["value"])
                except (KeyError, TypeError, ValueError):
                    continue
                if value != value:
                    continue
                fp = f"{rule.id}|{obs.get('target', '')}|{obs.get('item', '')}"
                if fp in seen:
                    continue
                seen.add(fp)
                self._step(rule, obs, fp, value, now)
        for fp in [fp for fp in self.pending if fp not in seen]:
            del self.pending[fp]
        self._suppress(now)
        self._housekeeping(seen, now)
        return self._take()

    def _step(self, rule: Rule, obs: Dict[str, Any], fp: str, value: float, now: float) -> None:
        alert = self.active.get(fp)
        level = rule.level(value)
        if alert is None:
            if level is None:
                self.pending.pop(fp, None)
                return
            since = self.pending.setdefault(fp, now)
            if now - since >= rule.for_seconds:
                del self.pending[fp]
                self._fire(rule, obs, fp, value, level, now)
            return
        alert.last_seen, alert.unseen_since, alert.value = now, None, value
        worse = max if rule.operator in (">", ">=") else min
        alert.peak_value = worse(alert.peak_value, value) if rule.operator in (">", ">=", "<", "<=") else value
        alert.target_name = obs.get("name") or alert.target_name
        if level:
            if alert.clear_since is not None:
                alert.clear_since = None
                self._flap(alert, now)
            self._severity(alert, level, now)
        elif rule.cleared(value):
            if alert.clear_since is None:
                alert.clear_since = now
            if now - alert.clear_since >= rule.recover_seconds:
                self._resolve(alert, "recovered", now)
        else:
            alert.clear_since = None

    def _message(self, rule: Rule, name: str, item: str, value: float) -> str:
        where = f"{name} ({item})" if item else name
        return f"{rule.name} : {where} — valeur {_fmt(value)} (seuil {rule.operator} {_fmt(rule.threshold)})"

    def _fire(self, rule: Rule, obs: Dict[str, Any], fp: str, value: float, level: str, now: float) -> None:
        name, item = obs.get("name") or obs["target"], str(obs.get("item", "") or "")
        message = self._message(rule, name, item, value)
        old = self.recent.pop(fp, None)
        if old and old.resolved_at is not None and now - old.resolved_at <= self.reopen_seconds:
            a = old
            a.state, a.resolved_at, a.resolve_reason, a.severity = "firing", None, "", level
            a.acked, a.clear_since, a.unseen_since, a.suppressed_by, a.silenced = False, None, None, None, False
            a.reopened += 1
            a.value, a.last_seen, a.message, a.target_name = value, now, message, name
            self.active[fp] = a
            self._flap(a, now)
            self._event(a, "reopened", now, data={"value": value})
            return
        a = Alert(id=uuid.uuid4().hex[:16], fingerprint=fp, rule_id=rule.id, rule_name=rule.name,
                  source=obs.get("source", ""), target=obs["target"], target_name=name, item=item,
                  metric=rule.metric, severity=level, started_at=now, value=value, peak_value=value,
                  threshold=rule.threshold, operator=rule.operator, message=message, last_seen=now)
        self.active[fp] = a
        self._event(a, "fired", now, data={"value": value, "threshold": rule.threshold, "operator": rule.operator})

    def _severity(self, a: Alert, level: str, now: float) -> None:
        if level == a.severity:
            return
        up = SEV_RANK[level] > SEV_RANK[a.severity]
        old, a.severity = a.severity, level
        self._event(a, "escalated" if up else "deescalated", now, data={"from": old, "to": level, "value": a.value})
        if up and a.acked:
            a.acked = False
            self._event(a, "unacked", now, comment="Sévérité aggravée : acquittement levé", author=SYSTEM)

    def _resolve(self, a: Alert, reason: str, now: float) -> None:
        a.state, a.resolved_at, a.resolve_reason, a.clear_since = "resolved", now, reason, None
        self.active.pop(a.fingerprint, None)
        self.recent[a.fingerprint] = a
        self._event(a, "resolved", now, data={"reason": reason, "duration_s": round(now - a.started_at),
                                              "peak": a.peak_value})

    def _flap(self, a: Alert, now: float) -> None:
        times = [t for t in self._flap_times.get(a.fingerprint, []) if now - t <= FLAP_WINDOW] + [now]
        self._flap_times[a.fingerprint] = times
        a.flaps = len(times)

    def _suppress(self, now: float) -> None:
        roots = {a.target: a for a in self.active.values() if a.metric in ROOT_METRICS}
        for a in self.active.values():
            root = roots.get(a.target)
            want = root.id if root is not None and a.metric not in ROOT_METRICS else None
            if want != a.suppressed_by:
                a.suppressed_by = want
                self._event(a, "suppressed" if want else "unsuppressed", now, author=SYSTEM,
                            comment=f"Cause racine : {root.rule_name}" if want else "Cause racine résolue")

    def _window(self, target: str, now: float) -> Optional[Maintenance]:
        return next((m for m in self.maintenance.values() if m.covers(target) and m.active_at(now)), None)

    def _housekeeping(self, seen: set, now: float) -> None:
        for fp, a in list(self.active.items()):
            rule = self.rules.get(a.rule_id)
            if rule is None or not rule.enabled:
                self._resolve(a, "rule_deleted" if rule is None else "rule_disabled", now)
                continue
            if fp not in seen and not a.suppressed_by:
                a.unseen_since = a.unseen_since if a.unseen_since is not None else now
                if now - a.unseen_since >= self.stale_seconds:
                    self._resolve(a, "no_data", now)
                    continue
            if a.acked and a.ack_until is not None and now >= a.ack_until:
                a.acked = False
                self._event(a, "ack_expired", now, author=SYSTEM, comment="Durée d'acquittement écoulée")
            window = self._window(a.target, now)
            if window and not a.silenced:
                a.silenced, a.silence_name = True, window.name
                self._event(a, "silenced", now, author=SYSTEM, comment=f"Maintenance : {window.name}")
            elif not window and a.silenced:
                a.silenced, a.silence_name = False, ""
                self._event(a, "unsilenced", now, author=SYSTEM, comment="Fin de maintenance")
        for fp in [fp for fp, a in self.recent.items() if a.resolved_at is None or now - a.resolved_at > self.reopen_seconds]:
            del self.recent[fp]
        for fp in [fp for fp, ts in self._flap_times.items() if not ts or now - ts[-1] > FLAP_WINDOW]:
            del self._flap_times[fp]

    # --- actions utilisateur ---------------------------------------------------------------------------------------
    def find(self, alert_id: str) -> Optional[Alert]:
        for a in self.active.values():
            if a.id == alert_id:
                return a
        return next((a for a in self.recent.values() if a.id == alert_id), None)

    def _active(self, alert_id: str) -> Alert:
        a = next((x for x in self.active.values() if x.id == alert_id), None)
        if a is None:
            raise LookupError("alerte active introuvable (déjà résolue ?)")
        return a

    def ack(self, alert_id: str, author: str, comment: str, until: Optional[float] = None, ip: str = "") -> Changes:
        author, comment = _clean(author, 80), _clean(comment, 1000)
        if not author:
            raise ValueError("nom de l'auteur requis")
        if not comment:
            raise ValueError("commentaire requis")
        now = self._clock()
        if until is not None and until <= now:
            raise ValueError("la fin de l'acquittement doit être dans le futur")
        a = self._active(alert_id)
        self._begin()
        a.acked, a.ack_by, a.ack_comment, a.ack_at, a.ack_until, a.ack_ip = True, author, comment, now, until, ip[:64]
        self._event(a, "acked", now, author=author, comment=comment, data={"until": until, "ip": ip[:64]})
        return self._take()

    def unack(self, alert_id: str, author: str, comment: str = "", ip: str = "") -> Changes:
        author = _clean(author, 80)
        if not author:
            raise ValueError("nom de l'auteur requis")
        a = self._active(alert_id)
        if not a.acked:
            raise ValueError("l'alerte n'est pas acquittée")
        self._begin()
        a.acked = False
        self._event(a, "unacked", self._clock(), author=author, comment=_clean(comment, 1000), data={"ip": ip[:64]})
        return self._take()

    def comment(self, alert_id: str, author: str, text: str, ip: str = "", fallback: Optional[Alert] = None) -> Changes:
        author, text = _clean(author, 80), _clean(text, 1000)
        if not author:
            raise ValueError("nom de l'auteur requis")
        if not text:
            raise ValueError("commentaire requis")
        a = self.find(alert_id) or fallback
        if a is None:
            raise LookupError("alerte introuvable")
        self._begin()
        a.notes += 1
        self._event(a, "comment", self._clock(), author=author, comment=text, data={"ip": ip[:64]})
        return self._take()

    # --- lecture ---------------------------------------------------------------------------------------------------
    def active_list(self) -> List[Dict[str, Any]]:
        order = sorted(self.active.values(), key=lambda a: (-SEV_RANK[a.severity], a.started_at))
        return [a.to_dict() for a in order]

    def counts(self) -> Dict[str, int]:
        c = {"active": 0, "to_handle": 0, "critical": 0, "warning": 0, "info": 0, "acked": 0, "silenced": 0,
             "suppressed": 0}
        for a in self.active.values():
            c["active"] += 1
            if a.needs_attention:
                c["to_handle"] += 1
                c[a.severity] += 1
            c["acked"] += a.acked
            c["silenced"] += a.silenced
            c["suppressed"] += bool(a.suppressed_by)
        return c

    # --- journal des changements -------------------------------------------------------------------------------------
    def _begin(self) -> None:
        self._touched, self._events = {}, []

    def _take(self) -> Changes:
        out = Changes([a.to_dict() for a in self._touched.values()], self._events)
        self._begin()
        return out

    def _event(self, a: Alert, kind: str, now: float, author: str = SYSTEM, comment: str = "",
               data: Optional[Dict[str, Any]] = None) -> None:
        a.updated_at = now
        self._touched[a.id] = a
        self._events.append({"id": uuid.uuid4().hex[:16], "alert_id": a.id, "t": now, "type": kind, "author": author,
                             "comment": comment, "severity": a.severity, "value": a.value, "data": data or {}})
