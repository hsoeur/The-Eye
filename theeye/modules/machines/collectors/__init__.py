"""Chargement automatique de tous les collecteurs du dossier."""
import importlib
import pkgutil

from .base import COLLECTORS, CollectError, Collector, normalize, register  # noqa: F401

for _info in pkgutil.iter_modules(__path__):
    if _info.name != "base":
        importlib.import_module(f"{__name__}.{_info.name}")
