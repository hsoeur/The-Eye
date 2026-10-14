"""Module Alertes : moteur de seuils, acquittement avec commentaire, maintenance et historique complet.

Le moteur (engine.py) est pur et vit en mémoire ; la base (MySQL ou SQLite) est l'historien, alimentée via un journal
d'écriture différée (journal.py) pour que l'évaluation ne dépende jamais de la disponibilité de la base.
"""
import csv
import io
import threading
import time
from typing import Any, Dict, List, Optional

from ...core.http import HttpError, Request, Response, Router
from ...core.module import Health, Module
from .engine import Alert, Changes, Engine
from .journal import Journal
from .rules import SEVERITIES, Maintenance, Rule, default_rules
from .store import SqlStore, StoreError, StoreUnavailable, unprotect

SNAPSHOT_EVERY = 60
CSV_COLUMNS = ["id", "state", "severity", "rule_name", "target_name", "item", "message", "started_at", "resolved_at",
               "resolve_reason", "peak_value", "threshold", "acked", "ack_by", "ack_comment", "ack_at", "flaps",
               "reopened", "notes"]
NOTIFY = {"fired": ("alert", None), "escalated": ("alert", None), "resolved": ("alert", "info"),
          "acked": ("alert", "info")}


def _iso(t: Any) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else ""


class AlertsModule(Module):
    id = "alerts"
    label = "Alertes"
    order = 5

    def __init__(self, ctx):
        super().__init__(ctx)
        cfg = ctx.config
        self.interval = max(5.0, float(cfg.get("interval_s", 15)))
        self.retention_days = max(1, int(cfg.get("retention_days", 365)))
        self.engine = Engine(stale_seconds=max(120.0, self.interval * 20))
        self.engine.set_rules(default_rules())
        self.lock = threading.RLock()
        self.snapshot = ctx.store("alerts_state")
        self.loaded = False
        self.dirty = False
        self.last_snapshot = 0.0
        self.last_eval = 0.0
        self.last_eval_ms = 0
        self.last_error = ""
        self.catalog: Dict[str, Any] = {"targets": {}, "metrics": {}}
        self.store: Optional[SqlStore] = None
        self.journal: Optional[Journal] = None
        self.config_error = ""
        self._build_store()
        self._restore_snapshot()

    # --- démarrage -----------------------------------------------------------------------------------------------
    def _build_store(self) -> None:
        db = self.ctx.config.get("db") or {}
        kind = db.get("type", "sqlite")
        try:
            password = db.get("password", "")
            if db.get("password_enc"):
                password = unprotect(self.ctx.runner, db["password_enc"]) or password
            self.store = SqlStore(kind, db, password, self.ctx.settings.data_dir / "alerts.db")
            self.journal = Journal(self.store, self.ctx.settings.data_dir / "alerts_outbox.jsonl")
        except ValueError as e:
            self.config_error = str(e)
            self.ctx.log.error("configuration de la base d'alertes invalide : %s", e)

    def _restore_snapshot(self) -> None:
        snap = self.snapshot.load()
        if not isinstance(snap, dict) or not snap:
            return
        try:
            if snap.get("rules"):
                self.engine.set_rules(Rule.from_dict(r) for r in snap["rules"])
            self.engine.set_maintenance(Maintenance.from_dict(m, m.get("id")) for m in snap.get("maintenance", []))
            self.engine.adopt(Alert.from_dict(a) for a in snap.get("active", []))
        except (ValueError, TypeError, KeyError):
            self.ctx.log.exception("instantané des alertes illisible, ignoré")

    def start(self) -> None:
        sch = self.ctx.scheduler
        sch.every("alerts.eval", self.interval, self._evaluate, immediate=False)
        if self.journal:
            sch.every("alerts.flush", 5, self._flush)
            sch.every("alerts.load", 30, self._try_load)
            sch.every("alerts.purge", 86400, self._purge, immediate=False)

    def stop(self) -> None:
        self._write_snapshot()
        if self.store:
            self.store.close()

    # --- base de données -----------------------------------------------------------------------------------------
    def _flush(self) -> None:
        self.journal.flush(limit=2000)

    def _try_load(self) -> None:
        """Charge règles, fenêtres et alertes actives depuis la base ; réessayé jusqu'au succès."""
        if self.loaded:
            return
        try:
            self.store.init()
            if not self.journal.flush():
                return
            cfg = self.store.load_config()
            active = self.store.load_active()
        except (StoreUnavailable, StoreError) as e:
            self.journal.last_error = str(e)
            return
        with self.lock:
            seeded = cfg["meta"].get("rules_seeded") == "1"
            if cfg["rules"] or seeded:
                self.engine.set_rules(r for r in (self._safe_rule(d) for d in cfg["rules"]) if r)
                self.engine.set_maintenance(m for m in (self._safe_maint(d) for d in cfg["maintenance"]) if m)
            else:
                self.journal.push([{"op": "rule", "d": r.to_dict()} for r in self.engine.rules.values()]
                                  + [{"op": "maint", "d": m.to_dict()} for m in self.engine.maintenance.values()]
                                  + [{"op": "meta", "d": {"k": "rules_seeded", "v": "1"}}])
            self.engine.adopt(Alert.from_dict(a) for a in active)
            self.loaded = self.dirty = True
        self.ctx.log.info("base d'alertes chargée (%d alerte(s) active(s))", len(active))

    @staticmethod
    def _safe_rule(d):
        try:
            return Rule.from_dict(d)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_maint(d):
        try:
            return Maintenance.from_dict(d, d.get("id"))
        except (ValueError, TypeError):
            return None

    def _purge(self) -> None:
        try:
            while self.store.purge(time.time() - self.retention_days * 86400) >= 5000:
                pass
        except (StoreUnavailable, StoreError) as e:
            self.ctx.log.warning("purge de l'historique impossible : %s", e)

    # --- évaluation ----------------------------------------------------------------------------------------------
    def _evaluate(self) -> None:
        t0 = time.monotonic()
        observations = self.ctx.collect_observations()
        with self.lock:
            self._update_catalog(observations)
            changes = self.engine.evaluate(observations)
            self._record(changes)
            self.last_eval, self.last_eval_ms = time.time(), round((time.monotonic() - t0) * 1000)
        self._write_snapshot()

    def _update_catalog(self, observations: List[Dict[str, Any]]) -> None:
        for o in observations:
            self.catalog["targets"][o.get("target", "")] = o.get("target_name") or o.get("target", "")
            self.catalog["metrics"].setdefault(o.get("metric", ""), {"source": o.get("source", ""),
                                                                      "unit": o.get("unit", "")})

    def _record(self, changes: Changes) -> None:
        """Persiste les changements et publie les évènements marquants sur le bus."""
        if not changes:
            return
        self.dirty = True
        if self.journal:
            self.journal.push([{"op": "alert", "d": a} for a in changes.alerts]
                              + [{"op": "event", "d": e} for e in changes.events])
        by_id = {a["id"]: a for a in changes.alerts}
        for e in changes.events:
            if e["type"] not in NOTIFY:
                continue
            a = by_id.get(e["alert_id"]) or {}
            sev = NOTIFY[e["type"]][1] or ("error" if a.get("severity") == "critical" else "warning")
            self.ctx.emit(e["type"], a.get("message", ""), sev, alert_id=e["alert_id"], target=a.get("target", ""))

    def _write_snapshot(self) -> None:
        if not (self.dirty or time.time() - self.last_snapshot > SNAPSHOT_EVERY):
            return
        with self.lock:
            data = {"rules": [r.to_dict() for r in self.engine.rules.values()],
                    "maintenance": [m.to_dict() for m in self.engine.maintenance.values()],
                    "active": [a.to_dict() for a in self.engine.active.values()]}
            self.dirty = False
        self.snapshot.save(data)
        self.last_snapshot = time.time()

    # --- API -----------------------------------------------------------------------------------------------------
    def register_routes(self, r: Router) -> None:
        r.get("", self._list)
        r.get("/status", lambda req: self._status())
        r.get("/history", self._history)
        r.get("/export.csv", self._export)
        r.get("/stats", self._stats)
        r.get("/catalog", self._catalog)
        r.get("/rules", lambda req: {"rules": [x.to_dict() for x in self.engine.rules.values()]})
        r.post("/rules", self._rule_save)
        r.put("/rules/{id}", self._rule_save)
        r.delete("/rules/{id}", self._rule_delete)
        r.get("/maintenance", self._maint_list)
        r.post("/maintenance", self._maint_save)
        r.put("/maintenance/{id}", self._maint_save)
        r.delete("/maintenance/{id}", self._maint_delete)
        r.get("/{id}", self._detail)
        r.post("/{id}/ack", self._ack)
        r.post("/{id}/unack", self._unack)
        r.post("/{id}/comment", self._comment)

    def _status(self) -> Dict[str, Any]:
        j = self.journal
        return {"last_eval": self.last_eval, "last_eval_ms": self.last_eval_ms, "interval": self.interval,
                "db": {"type": self.store.kind if self.store else "", "target": self.store.description if self.store else "",
                       "ok": bool(j and j.available), "loaded": self.loaded, "pending": j.pending() if j else 0,
                       "dropped": j.dropped if j else 0, "last_error": (j.last_error if j else "") or self.config_error,
                       "last_ok": j.last_ok if j else 0},
                "retention_days": self.retention_days}

    def _list(self, req: Request):
        with self.lock:
            return {"alerts": self.engine.active_list(), "counts": self.engine.counts(), "status": self._status(),
                    "maintenance_active": [m.to_dict() for m in self.engine.maintenance.values()
                                           if m.enabled and m.active_at(time.time())]}

    def _need_store(self) -> SqlStore:
        if not self.store:
            raise HttpError(503, "base d'alertes non configurée : " + self.config_error)
        return self.store

    def _db(self, fn):
        try:
            return fn(self._need_store())
        except StoreUnavailable:
            raise HttpError(503, "base d'alertes indisponible")
        except StoreError as e:
            raise HttpError(500, str(e))

    @staticmethod
    def _filters(req: Request) -> Dict[str, Any]:
        q, f = req.query, {}
        for key in ("state", "severity", "target", "rule", "q"):
            if q.get(key):
                f[key] = q[key]
        if f.get("severity") and f["severity"] not in SEVERITIES:
            raise HttpError(400, "sévérité invalide")
        if q.get("acked") in ("true", "false"):
            f["acked"] = q["acked"] == "true"
        try:
            for key in ("since", "until"):
                if q.get(key):
                    f[key] = float(q[key])
        except ValueError:
            raise HttpError(400, "date invalide")
        return f

    @staticmethod
    def _page(req: Request, default: int = 100):
        try:
            return min(1000, max(1, int(req.query.get("limit", default)))), max(0, int(req.query.get("offset", 0)))
        except ValueError:
            raise HttpError(400, "pagination invalide")

    def _history(self, req: Request):
        f, (limit, offset) = self._filters(req), self._page(req)
        rows, total = self._db(lambda s: s.query(f, limit, offset))
        return {"alerts": rows, "total": total}

    def _export(self, req: Request):
        f = self._filters(req)
        rows, _ = self._db(lambda s: s.query(f, 20000, 0))
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(CSV_COLUMNS)
        for r in rows:
            w.writerow([_iso(r[c]) if c.endswith("_at") else r.get(c, "") for c in CSV_COLUMNS])
        body = ("\ufeff" + out.getvalue()).encode("utf-8")
        return Response(200, body, "text/csv; charset=utf-8",
                        {"Content-Disposition": 'attachment; filename="alertes.csv"'})

    def _stats(self, req: Request):
        try:
            days = min(365, max(1, int(req.query.get("days", 30))))
        except ValueError:
            raise HttpError(400, "période invalide")
        return {"days": days, **self._db(lambda s: s.stats(time.time() - days * 86400))}

    def _catalog(self, req: Request):
        return {"targets": [{"target": k, "name": v} for k, v in sorted(self.catalog["targets"].items())],
                "metrics": [{"metric": k, **v} for k, v in sorted(self.catalog["metrics"].items())]}

    def _detail(self, req: Request):
        alert_id = req.params["id"]
        with self.lock:
            a = self.engine.find(alert_id)
            alert = a.to_dict() if a else None
        events: List[Dict[str, Any]] = []
        try:
            store = self._need_store()
            if alert is None:
                alert = store.get_alert(alert_id)
                if alert:
                    alert = Alert.from_dict(alert).to_dict()
            events = store.events(alert_id)
        except HttpError:
            pass
        except (StoreUnavailable, StoreError):
            if alert is None:
                raise HttpError(503, "base d'alertes indisponible")
        if alert is None:
            raise HttpError(404, "alerte introuvable")
        return {"alert": alert, "events": events}

    def _act(self, fn):
        with self.lock:
            try:
                changes = fn()
            except ValueError as e:
                raise HttpError(400, str(e))
            except LookupError as e:
                raise HttpError(404, str(e))
            self._record(changes)
            return {"ok": True, "alert": changes.alerts[0] if changes.alerts else None}

    @staticmethod
    def _until(body: Dict[str, Any]) -> Optional[float]:
        if body.get("until") in (None, "", 0):
            return None
        try:
            return float(body["until"])
        except (TypeError, ValueError):
            raise HttpError(400, "durée d'acquittement invalide")

    def _ack(self, req: Request):
        b = req.json()
        return self._act(lambda: self.engine.ack(req.params["id"], b.get("author", ""), b.get("comment", ""),
                                                 self._until(b), req.client))

    def _unack(self, req: Request):
        b = req.json()
        return self._act(lambda: self.engine.unack(req.params["id"], b.get("author", ""), b.get("comment", ""),
                                                   req.client))

    def _comment(self, req: Request):
        b = req.json()
        alert_id = req.params["id"]
        fallback = None
        with self.lock:
            known = self.engine.find(alert_id) is not None
        if not known:
            row = self._db(lambda s: s.get_alert(alert_id))
            fallback = Alert.from_dict(row) if row else None
        return self._act(lambda: self.engine.comment(alert_id, b.get("author", ""), b.get("text", b.get("comment", "")),
                                                     req.client, fallback))

    # --- règles et maintenance -----------------------------------------------------------------------------------
    def _rule_save(self, req: Request):
        rid = req.params.get("id")
        with self.lock:
            if rid and rid not in self.engine.rules:
                raise HttpError(404, "règle inconnue")
            try:
                rule = Rule.from_dict(req.json(), rid)
            except ValueError as e:
                raise HttpError(400, str(e))
            if not rid and rule.id in self.engine.rules:
                raise HttpError(409, "identifiant de règle déjà utilisé")
            self.engine.rules[rule.id] = rule
            self._push([{"op": "rule", "d": rule.to_dict()}])
        return rule.to_dict()

    def _rule_delete(self, req: Request):
        with self.lock:
            if self.engine.rules.pop(req.params["id"], None) is None:
                raise HttpError(404, "règle inconnue")
            self._push([{"op": "rule_del", "d": {"id": req.params["id"]}}])

    def _maint_list(self, req: Request):
        now = time.time()
        with self.lock:
            return {"windows": [{**m.to_dict(), "active": m.enabled and m.active_at(now)}
                                for m in self.engine.maintenance.values()]}

    def _maint_save(self, req: Request):
        mid, body = req.params.get("id"), req.json()
        with self.lock:
            if mid and mid not in self.engine.maintenance:
                raise HttpError(404, "fenêtre inconnue")
            try:
                m = Maintenance.from_dict(body, mid, str(body.get("author", "")))
            except ValueError as e:
                raise HttpError(400, str(e))
            self.engine.maintenance[m.id] = m
            self._push([{"op": "maint", "d": m.to_dict()}])
        return m.to_dict()

    def _maint_delete(self, req: Request):
        with self.lock:
            if self.engine.maintenance.pop(req.params["id"], None) is None:
                raise HttpError(404, "fenêtre inconnue")
            self._push([{"op": "maint_del", "d": {"id": req.params["id"]}}])

    def _push(self, ops: List[Dict[str, Any]]) -> None:
        self.dirty = True
        if self.journal:
            self.journal.push(ops)

    # --- santé ---------------------------------------------------------------------------------------------------
    def health(self) -> Health:
        with self.lock:
            c = self.engine.counts()
        stats = [{"label": "À traiter", "value": c["to_handle"]}, {"label": "Critiques", "value": c["critical"]},
                 {"label": "Acquittées", "value": c["acked"]}]
        stale = self.last_eval and time.time() - self.last_eval > self.interval * 4
        if c["critical"]:
            return Health("critical", f"{c['critical']} alerte(s) critique(s) à traiter", stats)
        if c["to_handle"]:
            return Health("warning", f"{c['to_handle']} alerte(s) à traiter", stats)
        if stale or (self.journal and not self.journal.available and self.journal.last_error) or self.config_error:
            return Health("warning", "Base d'alertes indisponible ou évaluation en retard", stats)
        return Health("ok", "Aucune alerte à traiter", stats)


MODULE = AlertsModule
