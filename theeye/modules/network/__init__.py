"""Module Réseau : découverte, inventaire et cartographie."""
import ipaddress
from pathlib import Path

from ...core.http import HttpError, Request, Router
from ...core.module import Health, Module
from .discovery import Probes
from .fingerprint import DEVICE_TYPES, PORTS, load_oui
from .service import NetworkService


class NetworkModule(Module):
    id = "network"
    label = "Réseau"
    order = 10

    def __init__(self, ctx):
        super().__init__(ctx)
        probes = Probes(ctx.runner, PORTS)
        self.service = NetworkService(ctx, probes, load_oui(Path(__file__).parent / "oui.json"))

    def start(self) -> None:
        minutes = int(self.ctx.config.get("scan_interval_min", 15))
        if minutes > 0:
            self.ctx.scheduler.every("network.scan", minutes * 60, self.service.scan, immediate=True)
        else:
            self.service.start_scan()

    def register_routes(self, r: Router) -> None:
        r.get("/state", lambda req: self.service.snapshot())
        r.post("/scan", self._scan)
        r.post("/device", self._device)
        r.post("/forget", self._forget)

    def _scan(self, req: Request):
        b = req.json()
        cidrs = [c for c in b.get("cidrs", []) if isinstance(c, str)]
        try:
            for c in cidrs:
                ipaddress.ip_network(c, strict=False)
        except ValueError:
            raise HttpError(400, "CIDR invalide")
        return {"ok": True, "started": self.service.start_scan(cidrs or None, bool(b.get("ports", True)))}

    def _device(self, req: Request):
        b = req.json()
        dtype = b.get("type")
        if dtype is not None and dtype not in DEVICE_TYPES:
            raise HttpError(400, "type inconnu")
        label = str(b["label"]) if "label" in b else None
        if not self.service.update_device(str(b.get("ip", "")), label, dtype):
            raise HttpError(404, "équipement inconnu")

    def _forget(self, req: Request):
        self.service.forget(str(req.json().get("ip", "")))

    def observations(self):
        # Seuls les équipements nommés par l'utilisateur sont considérés comme à surveiller.
        return [{"target": "net:" + d["ip"], "name": d["label"], "metric": "device_online",
                 "value": 1.0 if d.get("online", True) else 0.0}
                for d in self.service.snapshot()["devices"].values() if d.get("label")]

    def health(self) -> Health:
        s = self.service.snapshot()
        devs = list(s["devices"].values())
        online = sum(1 for d in devs if d["online"])
        new = sum(1 for d in devs if d.get("new"))
        stats = [{"label": "Équipements", "value": len(devs)}, {"label": "En ligne", "value": online},
                 {"label": "Hors ligne", "value": len(devs) - online}, {"label": "Nouveaux", "value": new}]
        if self.service.last_error:
            return Health("warning", "Dernier scan en échec", stats)
        if not devs:
            return Health("unknown", "Aucun scan terminé", stats)
        return Health("warning" if new else "ok", f"{online} en ligne sur {len(devs)}" + (f", {new} nouveau(x)" if new else ""), stats)


MODULE = NetworkModule
