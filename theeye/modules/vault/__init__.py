"""Module Coffre : mots de passe des comptes de production et machines/postes où ils sont utilisés.

Secrets chiffrés au repos (AES-256-GCM, clé dérivée par scrypt d'une phrase secrète jamais stockée).
Le coffre est verrouillé au démarrage et après inactivité ; toute consultation d'un secret est auditée.
"""
from ...core.http import Request, Router
from ...core.module import Health, Module
from .service import VaultService


class VaultModule(Module):
    id = "vault"
    label = "Coffre"
    order = 60

    def __init__(self, ctx):
        super().__init__(ctx)
        self.service = VaultService(ctx)

    def register_routes(self, r: Router) -> None:
        s = self.service
        r.get("", self._state)
        r.post("/setup", lambda q: s.setup(str(q.json().get("passphrase", "")), q.client))
        r.post("/unlock", lambda q: s.unlock(str(q.json().get("passphrase", "")), q.client))
        r.post("/lock", lambda q: s.lock_now(q.client))
        r.post("/passphrase", self._change_passphrase)
        r.post("/accounts", lambda q: (201, s.create(q.json(), q.client)))
        r.put("/accounts/{id}", lambda q: s.update(q.params["id"], q.json(), q.client))
        r.delete("/accounts/{id}", lambda q: s.delete(q.params["id"], q.client))
        r.post("/accounts/{id}/reveal", self._reveal)
        r.get("/audit", lambda q: {"audit": s.audit()})

    def _state(self, req: Request):
        st = self.service.status()
        return {**st, "accounts": self.service.list() if st["unlocked"] else [], "stale_days": self.service.stale_days}

    def _change_passphrase(self, req: Request):
        b = req.json()
        self.service.change_passphrase(str(b.get("old", "")), str(b.get("new", "")), req.client)

    def _reveal(self, req: Request):
        secret = self.service.reveal(req.params["id"], str(req.json().get("passphrase", "")), req.client)
        return {"secret": secret}

    def observations(self):
        if not self.service.initialized:
            return []
        return [{"target": "vault", "name": "Coffre", "metric": "vault_stale_secrets",
                 "value": float(self.service.stale_count())}]

    def health(self) -> Health:
        st = self.service.status()
        if not st["available"]:
            return Health("critical", "Dépendance manquante : cryptography")
        if not st["initialized"]:
            return Health("unknown", "Coffre non initialisé")
        stale = self.service.stale_count()
        stats = [{"label": "Comptes", "value": st["count"]}, {"label": "À renouveler", "value": stale}]
        state = "déverrouillé" if st["unlocked"] else "verrouillé"
        return Health("warning" if stale else "ok", f"{st['count']} compte(s), {state}"
                      + (f", {stale} à renouveler" if stale else ""), stats)


MODULE = VaultModule
