"""Contrat d'un collecteur de machine et registre des collecteurs disponibles.

Pour ajouter un type de machine (SNMP, agent HTTP, ...) : créer un fichier dans ce dossier avec une
sous-classe de `Collector` décorée par `@register`. Le formulaire d'ajout de l'interface est généré
depuis `fields`, aucune autre modification n'est nécessaire.

Schéma de métriques attendu de `collect()` (clés absentes = valeurs par défaut) :
  hostname, os, uptime_s, cpu (%), cores, mem_total, mem_used, net_rx, net_tx (octets cumulés),
  disks [{name,total,free}], procs [{pid,name,cpu,mem}], nproc,
  services [{name,display,state: running|stopped|failed,start}], ports [int], events [{t,src,msg}]
"""
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Type

from ....core.process import Runner

DEFAULTS: Dict[str, Any] = {"hostname": "", "os": "", "uptime_s": 0.0, "cpu": 0.0, "cores": 1, "mem_total": 0.0,
                            "mem_used": 0.0, "net_rx": 0.0, "net_tx": 0.0, "disks": [], "procs": [], "nproc": 0,
                            "services": [], "ports": [], "events": []}


class CollectError(Exception):
    pass


class Collector(ABC):
    kind: str = ""
    label: str = ""
    proc_cpu_unit: str = "%"
    # {"name","label","type": text|password,"placeholder","pattern","required","secret"}
    fields: List[Dict[str, Any]] = []

    def __init__(self, runner: Runner, local_ips: set):
        self.runner, self.local_ips = runner, local_ips

    @abstractmethod
    def collect(self, host: Dict[str, Any]) -> Dict[str, Any]:
        """Retourne les métriques ; lève CollectError avec un message lisible."""

    def protect(self, value: str) -> str:
        """Chiffre un secret avant stockage (par défaut : non supporté)."""
        raise ValueError("secrets non supportés pour ce type de machine")

    def build_options(self, body: Dict[str, Any]) -> Dict[str, Any]:
        opts = {}
        for f in self.fields:
            value = str(body.get(f["name"], "") or "").strip()
            if f.get("required") and not value:
                raise ValueError(f"{f['label']} requis")
            if value and f.get("pattern") and not re.fullmatch(f["pattern"], value):
                raise ValueError(f"{f['label']} invalide")
            opts[f["name"]] = self.protect(value) if value and f.get("secret") else value
        return opts

    def public_options(self, host: Dict[str, Any]) -> Dict[str, Any]:
        return {f["name"]: host.get(f["name"], "") for f in self.fields if not f.get("secret")}

    @classmethod
    def describe(cls) -> Dict[str, Any]:
        return {"kind": cls.kind, "label": cls.label, "proc_cpu_unit": cls.proc_cpu_unit, "fields": cls.fields}


def normalize(m: Dict[str, Any]) -> Dict[str, Any]:
    out = {**DEFAULTS, **{k: v for k, v in m.items() if v is not None}}
    out["cpu"] = float(out["cpu"] or 0)
    return out


COLLECTORS: Dict[str, Type[Collector]] = {}


def register(cls: Type[Collector]) -> Type[Collector]:
    if not cls.kind or cls.kind in COLLECTORS:
        raise ValueError(f"collecteur invalide ou en double : {cls.kind!r}")
    COLLECTORS[cls.kind] = cls
    return cls
