"""Module Machines : supervision détaillée de serveurs via des collecteurs interchangeables."""
from ...core.http import HttpError, Request, Router
from ...core.module import Health, Module
from ...core.netinfo import local_networks
from .service import MachineService


class MachinesModule(Module):
    id = "machines"
    label = "Machines"
    order = 30

    def __init__(self, ctx):
        super().__init__(ctx)
        self.local_ips: set = set()
        self.service = MachineService(ctx, self.local_ips)

    def start(self) -> None:
        self.local_ips.update(ip for ip, _ in local_networks(self.ctx.runner)[0])
        self.ctx.scheduler.every("machines.tick", 1, self.service.tick)

    def register_routes(self, r: Router) -> None:
        r.get("", lambda req: {"hosts": self.service.view(), "types": self.service.types()})
        r.post("", self._add)
        r.delete("/{id}", self._remove)

    def _add(self, req: Request):
        try:
            return {"id": self.service.add(req.json())}
        except ValueError as e:
            raise HttpError(400, str(e))

    def _remove(self, req: Request):
        if not self.service.remove(req.params["id"]):
            raise HttpError(404, "machine inconnue")

    def observations(self):
        return self.service.observations()

    def health(self) -> Health:
        c = self.service.counts()
        stats = [{"label": "Machines", "value": c["total"]}, {"label": "Injoignables", "value": c["down"]},
                 {"label": "Services en défaut", "value": c["service_faults"]}]
        if not c["total"]:
            return Health("unknown", "Aucune machine configurée", stats)
        if c["down"]:
            return Health("critical", f"{c['down']} machine(s) injoignable(s)", stats)
        if c["service_faults"]:
            return Health("warning", f"{c['service_faults']} service(s) en défaut", stats)
        return Health("ok", f"{c['total']} machine(s) opérationnelle(s)", stats)


MODULE = MachinesModule
