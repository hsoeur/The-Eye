"""Assemblage de l'application : noyau + modules découverts."""
import logging
import logging.handlers
import signal
import threading
import time
from typing import List, Optional, Type

from . import __version__
from .core.config import Settings, parse_args
from .core.events import EventBus
from .core.http import Request, Router, Server, StaticFiles
from .core.module import Module, ModuleManager, Shared, discover
from .core.process import Runner
from .core.scheduler import Scheduler
from .core.storage import JsonStore

WEB_DIR = __import__("pathlib").Path(__file__).parent / "web"


class App:
    def __init__(self, settings: Settings, module_classes: Optional[List[Type[Module]]] = None):
        self.settings = settings
        self.started = time.time()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.bus = EventBus(JsonStore(settings.data_dir / "events.json", list))
        self.scheduler = Scheduler()
        self.manager = ModuleManager(Shared(settings, self.bus, self.scheduler, Runner()),
                                     discover() if module_classes is None else module_classes)
        self.router, self.static = Router(), StaticFiles()
        self.static.mount("/", WEB_DIR)
        self._core_routes()
        self.manager.register(self.router, self.static)
        self.server = Server(settings.host, settings.port, self.router, self.static)

    def _core_routes(self) -> None:
        r = self.router
        r.get("/api/health", lambda req: {"status": "ok", "version": __version__})
        r.get("/api/modules", lambda req: {"modules": self.manager.manifest(), "version": __version__})
        r.get("/api/overview", self._overview)
        r.get("/api/events", self._events)
        r.get("/api/system", self._system)

    def _overview(self, req: Request):
        return {"modules": self.manager.manifest(), "events": self.bus.recent(15), "now": time.time()}

    def _events(self, req: Request):
        try:
            limit = max(1, min(500, int(req.query.get("limit", 100))))
        except ValueError:
            limit = 100
        return {"events": self.bus.recent(limit, req.query.get("source"), req.query.get("severity")), "now": time.time()}

    def _system(self, req: Request):
        return {"version": __version__, "uptime_s": time.time() - self.started, "jobs": self.scheduler.status(),
                "module_errors": self.manager.errors, "routes": self.router.paths()}

    def run(self) -> None:
        self.scheduler.start()
        self.manager.start()
        self.server.start_background()
        logging.getLogger("eye").info("The Eye %s -> http://localhost:%d (modules : %s)", __version__,
                                      self.server.port, ", ".join(self.manager.modules) or "aucun")
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: stop.set())
            except ValueError:
                pass
        stop.wait()
        self.shutdown()

    def shutdown(self) -> None:
        logging.getLogger("eye").info("arrêt en cours")
        self.server.shutdown()
        self.manager.stop()
        self.scheduler.stop()


def setup_logging(settings: Settings) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    root = logging.getLogger("eye")
    root.setLevel(settings.log_level)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)
    log_dir = settings.data_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(log_dir / "eye.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass


def main(argv: Optional[List[str]] = None) -> None:
    settings = parse_args(argv)
    setup_logging(settings)
    App(settings).run()
