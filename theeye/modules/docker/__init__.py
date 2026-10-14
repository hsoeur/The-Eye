"""Module Docker : containers, ressources, logs et actions optionnelles."""
import threading
import time
from typing import Any, Dict, List

from ...core.http import HttpError, Request, Router
from ...core.module import Health, Module
from .client import ACTIONS, ID_RE, DockerClient, DockerUnavailable

HISTORY_POINTS = 90


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

    def start(self) -> None:
        self.ctx.scheduler.every("docker.poll", float(self.ctx.config.get("interval_s", 2)), self.poll)

    def poll(self) -> None:
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
        if not d["t"]:
            return []
        out = [{"target": "docker-host", "name": "Hôte Docker", "metric": "docker_available",
                "value": 1.0 if d["available"] else 0.0}]
        for c in d["containers"]:
            base = {"target": "container:" + c["name"], "name": "Container " + c["name"]}
            out.append({**base, "metric": "container_fault", "value": 1.0 if c["fault"] else 0.0})
            out.append({**base, "metric": "container_cpu_pct", "value": float(c.get("cpu") or 0)})
            out.append({**base, "metric": "container_mem_pct", "value": float(c.get("mem_pct") or 0)})
        return out

    def health(self) -> Health:
        with self.lock:
            d = dict(self.data)
        if not d["t"]:
            return Health("unknown", "En attente de la première mesure")
        if not d["available"]:
            return Health("critical", f"Docker indisponible : {d['error']}")
        cs = d["containers"]
        running = sum(1 for c in cs if c["state"] == "running")
        faults = sum(1 for c in cs if c["fault"])
        stats = [{"label": "Containers", "value": len(cs)}, {"label": "Actifs", "value": running},
                 {"label": "En défaut", "value": faults}]
        return Health("critical" if faults else "ok",
                      f"{running}/{len(cs)} actifs" + (f", {faults} en défaut" if faults else ""), stats)


MODULE = DockerModule
