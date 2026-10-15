"""Contrat des modules de supervision, contexte injecté et gestionnaire de cycle de vie.

Pour ajouter un module : créer le package theeye/modules/<id>/ dont __init__.py expose
`MODULE = MaClasse` (sous-classe de `Module`) ; il est découvert automatiquement.
"""
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .config import Settings
from .events import EventBus
from .http import Router, StaticFiles
from .process import Runner
from .scheduler import Scheduler
from .storage import JsonStore

log = logging.getLogger("eye.modules")
STATUSES = ("ok", "warning", "critical", "unknown")


@dataclass
class Health:
    """Résumé d'état d'un module, affiché dans la vue d'ensemble."""
    status: str = "unknown"
    summary: str = ""
    stats: List[Dict[str, Any]] = field(default_factory=list)  # [{"label": "...", "value": ...}]

    def to_dict(self) -> Dict[str, Any]:
        return {"status": self.status if self.status in STATUSES else "unknown",
                "summary": self.summary, "stats": self.stats}


@dataclass
class Shared:
    settings: Settings
    bus: EventBus
    scheduler: Scheduler
    runner: Runner
    manager: Any = None


class Context:
    """Ce qu'un module a le droit de connaître du reste de l'application."""

    def __init__(self, shared: Shared, module_id: str):
        self.module_id = module_id
        self.settings = shared.settings
        self.config: Dict[str, Any] = shared.settings.module(module_id)
        self.scheduler = shared.scheduler
        self.runner = shared.runner
        self.bus = shared.bus
        self._shared = shared
        self.log = logging.getLogger(f"eye.{module_id}")

    def store(self, name: str, default=dict) -> JsonStore:
        return JsonStore(self.settings.data_dir / f"{name}.json", default)

    def emit(self, kind: str, message: str, severity: str = "info", **data: Any) -> None:
        self.bus.publish(self.module_id, kind, message, severity, **data)

    def peer(self, module_id: str) -> Optional["Module"]:
        """Autre module actif (ou None) ; à utiliser en lecture seule et sans en dépendre pour fonctionner."""
        manager = self._shared.manager
        return manager.modules.get(module_id) if manager else None

    def collect_observations(self) -> List[Dict[str, Any]]:
        """Mesures de tous les modules (voir Module.observations), pour le moteur d'alertes."""
        manager = self._shared.manager
        return manager.observations() if manager else []


class Module:
    id: str = ""
    label: str = ""
    order: int = 100

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def start(self) -> None:
        """Démarre les tâches de fond (via ctx.scheduler)."""

    def stop(self) -> None:
        """Libère les ressources."""

    def register_routes(self, router: Router) -> None:
        """Déclare les routes ; le routeur reçu est déjà préfixé par /api/<id>."""

    def health(self) -> Health:
        return Health()

    def observations(self) -> List[Dict[str, Any]]:
        """Mesures courantes évaluables par le moteur d'alertes, sans que le module le connaisse.

        Chaque mesure : {"source", "target", "name", "metric", "value": float, "item": str (optionnel)}.
        `target` identifie l'objet supervisé (stable), `item` un sous-élément (disque, service...).
        """
        return []


def discover(package: str = "theeye.modules") -> List[Type[Module]]:
    pkg = importlib.import_module(package)
    found = []
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        try:
            cls = importlib.import_module(f"{package}.{info.name}").MODULE
            if not (isinstance(cls, type) and issubclass(cls, Module) and cls.id):
                raise TypeError("MODULE doit être une sous-classe de Module avec un id")
            found.append(cls)
        except Exception:
            log.exception("module %s ignoré (chargement impossible)", info.name)
    return sorted(found, key=lambda c: (c.order, c.id))


class ModuleManager:
    """Instancie, démarre et isole les modules : la panne de l'un n'arrête pas les autres."""

    def __init__(self, shared: Shared, classes: List[Type[Module]]):
        self.shared = shared
        self.modules: Dict[str, Module] = {}
        self.errors: Dict[str, str] = {}
        shared.manager = self
        disabled = set(shared.settings.disabled_modules)
        for cls in classes:
            if cls.id in disabled:
                log.info("module %s désactivé par la configuration", cls.id)
                continue
            try:
                self.modules[cls.id] = cls(Context(shared, cls.id))
            except Exception as e:
                log.exception("initialisation du module %s impossible", cls.id)
                self.errors[cls.id] = str(e)

    def _safe(self, mod: Module, action: str, fn) -> None:
        try:
            fn()
        except Exception as e:
            log.exception("module %s : %s en erreur", mod.id, action)
            self.errors[mod.id] = f"{action}: {e}"

    def register(self, router: Router) -> None:
        for mod in self.modules.values():
            self._safe(mod, "routes", lambda m=mod: m.register_routes(router.scoped(f"/api/{m.id}")))

    def start(self) -> None:
        for mod in self.modules.values():
            self._safe(mod, "start", mod.start)

    def stop(self) -> None:
        for mod in reversed(list(self.modules.values())):
            self._safe(mod, "stop", mod.stop)

    def observations(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for mod in self.modules.values():
            if mod.id in self.errors:
                continue
            try:
                for o in mod.observations():
                    out.append({"source": mod.id, **o})
            except Exception:
                log.exception("observations() du module %s en erreur", mod.id)
        return out

    def health(self, mod: Module) -> Dict[str, Any]:
        if mod.id in self.errors:
            return Health("critical", "Module en erreur : " + self.errors[mod.id][:120]).to_dict()
        try:
            return mod.health().to_dict()
        except Exception as e:
            log.exception("health() du module %s en erreur", mod.id)
            return Health("unknown", f"Indisponible ({e})"[:140]).to_dict()

    def manifest(self) -> List[Dict[str, Any]]:
        return [{"id": m.id, "label": m.label,
                 "health": self.health(m)} for m in self.modules.values()]
