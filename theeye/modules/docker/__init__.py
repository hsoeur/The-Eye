"""Module Docker : containers, ressources, logs, actions optionnelles et watchdog du moteur.

Deux cadences : une sonde de santé légère (`docker.watchdog`) et un poll d'inventaire/stats plus lourd
(`docker.poll`), suspendu tant que le moteur est déclaré figé.
"""
import os
import threading
import time
from dataclasses import replace
from typing import Any, Dict, List, Optional

from ...core.http import HttpError, Request, Router
from ...core.module import Health, Module
from .client import ACTIONS, ID_RE, DockerClient, DockerUnavailable
from .incident import PS_UTF8, IncidentCapture
from .recovery import Recoverer
from .watchdog import (DEGRADED, HEALTHY, HUNG, PROBE_CMD, RECOVERING, STATE_CODES, RecoveryGuard, Watchdog,
                       WatchdogConfig, classify, docker_is_local)

HISTORY_POINTS = 90
RECOVERY_TIMEOUT_S = 600.0
DESKTOP_REFRESH_S = 600.0
HOST = {"target": "docker-host", "name": "Hôte Docker"}
DESKTOP_START_PS = PS_UTF8 + (
    "$p = Get-Process 'Docker Desktop' | Sort-Object StartTime | Select-Object -First 1\n"
    "if ($p) { [int64]([DateTimeOffset]$p.StartTime).ToUnixTimeSeconds() }")


class DockerModule(Module):
    id = "docker"
    label = "Docker"
    order = 20

    def __init__(self, ctx):
        super().__init__(ctx)
        self.client = DockerClient(ctx.runner)
        self.actions_enabled = bool(ctx.config.get("actions", False))
        self.lock = threading.Lock()
        self.data: Dict[str, Any] = {"available": False, "error": "", "containers": [], "history": {}, "t": 0}
        self.cfg = WatchdogConfig.from_dict(ctx.config)
        if self.cfg.ignored:
            ctx.log.warning("configuration docker : valeurs invalides ignorées (%s)", ", ".join(self.cfg.ignored))
        self.wd = Watchdog(self.cfg, emit=ctx.emit)
        self.incidents = IncidentCapture(ctx.runner, ctx.settings.data_dir / "incidents", self.cfg.max_incidents)
        self.recoverer = Recoverer(ctx.runner)
        self.state_store = ctx.store("docker_watchdog")
        saved = self.state_store.load()
        if isinstance(saved, dict) and isinstance(saved.get("auto_recover"), bool):
            self.cfg = replace(self.cfg, auto_recover=saved["auto_recover"])
        self.guard = RecoveryGuard(self.cfg, history=self._saved_recoveries())
        self.local, self.local_reason = docker_is_local()
        self.work = threading.Lock()  # une seule capture ou relance à la fois
        self.recovering_now = False
        self.recovery: Dict[str, Any] = {"state": "", "started": 0.0, "detail": ""}
        self.recovery_note = ""
        self.last_capture: Dict[str, Any] = {}
        self.desktop_started = 0.0
        self._desktop_checked = 0.0

    def start(self) -> None:
        self.ctx.scheduler.every("docker.watchdog", self.cfg.probe_interval_s, self.watch)
        self.ctx.scheduler.every("docker.poll", self.cfg.interval_s, self.poll)

    # --- watchdog -------------------------------------------------------------------------------------------------
    def watch(self) -> None:
        t0 = time.monotonic()
        r = self.ctx.runner.run(PROBE_CMD, self.cfg.probe_timeout_s)
        dt = time.monotonic() - t0
        kind, detail = classify(r, dt, self.cfg)
        self.wd.record(kind, dt, detail, r.code)
        if self.wd.take_capture():
            self.ctx.scheduler.submit(self._capture_auto)
        self._track_recovery()
        self._maybe_recover()
        self._refresh_desktop_start()

    def _capture_auto(self) -> None:
        detail = (self.wd.last or {}).get("detail", "")
        if self._capture(f"moteur figé : {detail}", wait=True):
            self.wd.mark_capture_finished()
        else:
            self.wd.retry_capture()

    def _capture(self, reason: str, wait: bool) -> Optional[Dict[str, Any]]:
        if not self.work.acquire(timeout=120 if wait else 0):
            return None
        try:
            summary = self.incidents.capture(reason, self.wd.state, self.wd.snapshot()["history"],
                                             {"docker_server_last_ok": self.wd.last_ok_version})
            self.last_capture = summary
            failed = [k for k, v in summary["steps"].items() if not v.get("ok")]
            msg = f"Preuves capturées : {summary['path'] or summary.get('error', '')}"
            self.ctx.emit("docker_incident_captured", msg, "warning" if failed or not summary["path"] else "info",
                          path=summary["path"], reason=reason, failed_steps=failed)
            return summary
        finally:
            self.work.release()

    def _in_maintenance(self) -> bool:
        check = getattr(self.ctx.peer("alerts"), "in_maintenance", None)
        try:
            return bool(check and check(HOST["target"]))
        except Exception:
            return False

    def _maybe_recover(self) -> None:
        cfg = self.cfg
        if not cfg.auto_recover or self.wd.state != HUNG or self.wd.hung_for() < cfg.recover_after_s:
            return
        note = ""
        if not self.local:
            note = "relance automatique indisponible : " + self.local_reason
        elif self.wd.cli_missing:
            note = "CLI docker introuvable : relance inutile"
        elif cfg.capture_on_hung and not self.wd.capture_finished:
            note = "en attente de la capture des preuves"
        elif self._in_maintenance():
            note = "fenêtre de maintenance active : relance suspendue"
        else:
            allowed, why = self.guard.allow()
            note = "" if allowed else why
        self.recovery_note = note
        if note or not self.work.acquire(blocking=False):
            return
        self.ctx.scheduler.submit(self._recover)

    def _recover(self) -> None:
        """Appelé avec `self.work` acquis ; le libère."""
        try:
            self.guard.record()
            self._save_state()
            self.recovering_now = True
            self.wd.begin_recovery()
            self.recovery = {"state": "running", "started": time.time(), "detail": ""}
            self.ctx.emit("docker_recovery_started", "Relance automatique de Docker Desktop (moteur figé)", "warning")
            ok, detail = self.recoverer.run()
            self.recovery["detail"] = detail
            if ok:
                self._desktop_checked = 0.0
            else:
                self._recovery_failed(detail)
                self.wd.abort_recovery()
        except Exception as e:
            self.ctx.log.exception("relance de Docker en erreur")
            self._recovery_failed(str(e))
            self.wd.abort_recovery()
        finally:
            self.recovering_now = False
            self.work.release()

    def _recovery_failed(self, detail: str) -> None:
        self.recovery.update(state="failed", ended=time.time(), detail=detail)
        self.ctx.emit("docker_recovery_failed", f"Relance de Docker Desktop en échec : {detail}", "critical", detail=detail)

    def _track_recovery(self) -> None:
        if self.recovery.get("state") != "running" or self.recovering_now:
            return
        if self.wd.state == HEALTHY:
            self.recovery.update(state="done", ended=time.time())
            self.ctx.emit("docker_recovery_done", "Docker Desktop relancé, moteur rétabli", "ok")
            self.ctx.scheduler.submit(self._report_exited)
        elif time.time() - self.recovery["started"] > RECOVERY_TIMEOUT_S:
            self._recovery_failed("le moteur ne répond toujours pas après la relance")

    def _report_exited(self) -> None:
        try:
            names = self.client.crashed_without_restart()
        except DockerUnavailable:
            return
        if names:
            self.ctx.emit("docker_containers_exited",
                          f"{len(names)} container(s) arrêté(s) (Exited 255) sans politique restart, à redémarrer "
                          f"manuellement : {', '.join(names[:15])}", "info", containers=names)

    def _refresh_desktop_start(self) -> None:
        if os.name != "nt" or time.time() - self._desktop_checked < DESKTOP_REFRESH_S:
            return
        self._desktop_checked = time.time()
        self.ctx.scheduler.submit(self._read_desktop_start)

    def _read_desktop_start(self) -> None:
        r = self.ctx.runner.powershell(DESKTOP_START_PS, 15)
        if r.ok and r.out.strip().isdigit():
            self.desktop_started = float(r.out.strip())

    def _save_state(self) -> None:
        self.state_store.save({"recoveries": self.guard.history, "auto_recover": self.cfg.auto_recover})

    def _set_auto_recover(self, req: Request):
        if not self.actions_enabled:
            raise HttpError(403, "actions désactivées (lancer avec --docker-actions)")
        enabled = req.json().get("enabled")
        if not isinstance(enabled, bool):
            raise HttpError(400, "« enabled » doit être un booléen")
        self.cfg = replace(self.cfg, auto_recover=enabled)
        self.recovery_note = ""
        self._save_state()
        self.ctx.emit("docker_auto_recover_changed", "Relance automatique " + ("activée" if enabled else "désactivée"),
                      "info", enabled=enabled)
        return {"ok": True, "enabled": enabled}

    def _saved_recoveries(self) -> List[float]:
        saved = self.state_store.load()
        items = saved.get("recoveries", []) if isinstance(saved, dict) else []
        return items if isinstance(items, list) else []

    # --- inventaire et statistiques (lourd) -----------------------------------------------------------------------
    def poll(self) -> None:
        if self.wd.state == HUNG or self.recovering_now:
            with self.lock:
                self.data.update(available=False, containers=[], t=self.data["t"] or time.time(),
                                 error="Moteur Docker figé : sondage détaillé suspendu (voir l'onglet Moteur)")
            return
        try:
            cs = self.client.containers()
        except DockerUnavailable as e:
            with self.lock:
                self.data.update(available=False, error=str(e)[:200], containers=[])
            return
        now = time.time()
        with self.lock:
            self._detect_changes(self.data["containers"] if self.data["available"] else None, cs)
            hist = self.data["history"]
            for c in cs:
                h = hist.setdefault(c["id"], [])
                h.append([round(now), c["cpu"], c["mem_pct"]])
                del h[:-HISTORY_POINTS]
            for gone in set(hist) - {c["id"] for c in cs}:
                del hist[gone]
            self.data.update(available=True, error="", containers=cs, t=now)

    def _detect_changes(self, old: List[Dict[str, Any]], new: List[Dict[str, Any]]) -> None:
        if old is None:
            return
        before = {c["name"]: c for c in old}
        for c in new:
            o = before.get(c["name"])
            if not o:
                self.ctx.emit("container_new", f"Container {c['name']} créé", "info", name=c["name"])
            elif c["fault"] and not o["fault"]:
                self.ctx.emit("container_fault", f"Container {c['name']} en défaut ({c['status']})", "critical", name=c["name"])
            elif o["fault"] and not c["fault"]:
                self.ctx.emit("container_recovered", f"Container {c['name']} rétabli", "ok", name=c["name"])
            elif o["state"] == "running" and c["state"] != "running" and not c["fault"]:
                self.ctx.emit("container_stopped", f"Container {c['name']} arrêté", "warning", name=c["name"])
        for name in set(before) - {c["name"] for c in new}:
            self.ctx.emit("container_removed", f"Container {name} supprimé", "info", name=name)

    def register_routes(self, r: Router) -> None:
        r.get("", self._state)
        r.get("/logs", self._logs)
        r.post("/action", self._action)
        r.get("/watchdog", self._watchdog)
        r.post("/watchdog/capture", self._manual_capture)
        r.post("/watchdog/auto-recover", self._set_auto_recover)

    def _watchdog(self, req: Request):
        snap = self.wd.snapshot()
        return {**snap, "latency_s": (snap["last"] or {}).get("latency_s"), "config": self.cfg.to_dict(),
                "incidents": self.incidents.list_incidents(10), "desktop_started": self.desktop_started,
                "recoveries": {**self.guard.summary(), "enabled": self.cfg.auto_recover, "local": self.local,
                               "local_reason": self.local_reason, "note": self.recovery_note,
                               "current": self.recovery, "in_maintenance": self._in_maintenance()},
                "busy": self.work.locked(), "actions": self.actions_enabled, "now": time.time()}

    def _manual_capture(self, req: Request):
        if not self.actions_enabled:
            raise HttpError(403, "actions désactivées (lancer avec --docker-actions)")
        if self.work.locked():
            raise HttpError(409, "une capture ou une relance est déjà en cours")
        self.ctx.scheduler.submit(self._capture, "capture manuelle", False)
        return {"ok": True}

    def _state(self, req: Request):
        with self.lock:
            return {**self.data, "actions": self.actions_enabled, "now": time.time()}

    def _logs(self, req: Request):
        cid = req.query.get("id", "")
        if not ID_RE.fullmatch(cid):
            raise HttpError(400, "id invalide")
        return {"logs": self.client.logs(cid)}

    def _action(self, req: Request):
        if not self.actions_enabled:
            raise HttpError(403, "actions désactivées (lancer avec --docker-actions)")
        b = req.json()
        cid, act = str(b.get("id", "")), b.get("action")
        if not ID_RE.fullmatch(cid) or act not in ACTIONS:
            raise HttpError(400, "requête invalide")
        res = self.client.action(cid, act)
        self.ctx.emit("container_action", f"Action {act} sur {cid[:12]}", "info", id=cid, action=act, ok=res.ok)
        if not res.ok:
            return 500, {"ok": False, "out": (res.out + res.err)[-500:]}
        return {"ok": True}

    def observations(self):
        with self.lock:
            d = dict(self.data)
        out: List[Dict[str, Any]] = []
        last = self.wd.last
        if last:
            out += [{**HOST, "metric": "docker_engine_latency_s", "value": float(last["latency_s"]), "unit": "s"},
                    {**HOST, "metric": "docker_engine_state", "value": float(STATE_CODES[self.wd.state])},
                    {**HOST, "metric": "docker_engine_hung", "value": 1.0 if self.wd.state == HUNG else 0.0}]
        if not d["t"]:
            return out
        out.append({**HOST, "metric": "docker_available", "value": 1.0 if d["available"] else 0.0})
        for c in d["containers"]:
            base = {"target": "container:" + c["name"], "name": "Container " + c["name"]}
            out.append({**base, "metric": "container_fault", "value": 1.0 if c["fault"] else 0.0})
            out.append({**base, "metric": "container_cpu_pct", "value": float(c.get("cpu") or 0)})
            out.append({**base, "metric": "container_mem_pct", "value": float(c.get("mem_pct") or 0)})
        return out

    def health(self) -> Health:
        with self.lock:
            d = dict(self.data)
        state = self.wd.state
        latency = self.wd.latency()
        stats = [{"label": "Moteur", "value": state}]
        if latency is not None:
            stats.append({"label": "Latence", "value": f"{latency:.1f} s"})
        extra = ""
        if self.cfg.auto_recover and not self.local:
            stats.append({"label": "Relance auto", "value": "indisponible (Docker distant)"})
            extra = f" · relance auto indisponible : {self.local_reason}"
        if state == HUNG:
            return Health("critical", f"Moteur Docker figé depuis {int(self.wd.hung_for() // 60)} min{extra}", stats)
        if state == RECOVERING:
            return Health("warning", "Moteur Docker en cours de rétablissement" + extra, stats)
        if state == DEGRADED:
            return Health("warning", f"Moteur Docker dégradé (réponse en {latency or 0:.1f} s){extra}", stats)
        if not d["t"]:
            return Health("unknown", "En attente de la première mesure", stats)
        if not d["available"]:
            return Health("critical", f"Docker indisponible : {d['error']}", stats)
        cs = d["containers"]
        running = sum(1 for c in cs if c["state"] == "running")
        faults = sum(1 for c in cs if c["fault"])
        stats += [{"label": "Containers", "value": len(cs)}, {"label": "Actifs", "value": running},
                  {"label": "En défaut", "value": faults}]
        return Health("critical" if faults else "ok",
                      f"{running}/{len(cs)} actifs" + (f", {faults} en défaut" if faults else "") + extra, stats)


MODULE = DockerModule
