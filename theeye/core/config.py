"""Configuration : valeurs par défaut < data/config.json < arguments de ligne de commande."""
import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    host: str = "0.0.0.0"
    port: int = 8765
    data_dir: Path = ROOT / "data"
    log_level: str = "INFO"
    disabled_modules: List[str] = field(default_factory=list)
    modules: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def module(self, module_id: str) -> Dict[str, Any]:
        return self.modules.get(module_id, {})


def _read_file(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        raise SystemExit(f"config.json invalide ({path}): {e}")


def parse_args(argv: Optional[List[str]] = None) -> Settings:
    ap = argparse.ArgumentParser(description="The Eye - supervision")
    ap.add_argument("--host", help="adresse d'écoute (défaut 0.0.0.0)")
    ap.add_argument("--port", type=int, help="port d'écoute (défaut 8765)")
    ap.add_argument("--data-dir", help="dossier de données (défaut ./data)")
    ap.add_argument("--log-level", help="DEBUG, INFO, WARNING...")
    ap.add_argument("--auto", type=int, help="re-scan réseau toutes les N minutes (0 = off)")
    ap.add_argument("--docker-actions", action="store_true",
                    help="autorise start/stop/restart des containers depuis l'interface")
    ap.add_argument("--disable", action="append", default=[], metavar="MODULE", help="désactive un module")
    a = ap.parse_args(argv)

    data_dir = Path(a.data_dir or os.environ.get("EYE_DATA_DIR") or ROOT / "data")
    cfg = _read_file(data_dir / "config.json")
    modules = {k: dict(v) for k, v in (cfg.get("modules") or {}).items() if isinstance(v, dict)}
    if a.auto is not None:
        modules.setdefault("network", {})["scan_interval_min"] = a.auto
    if a.docker_actions:
        modules.setdefault("docker", {})["actions"] = True

    return Settings(
        host=a.host or cfg.get("host", "0.0.0.0"),
        port=a.port or int(cfg.get("port", 8765)),
        data_dir=data_dir,
        log_level=(a.log_level or cfg.get("log_level", "INFO")).upper(),
        disabled_modules=list(dict.fromkeys([*(cfg.get("disabled_modules") or []), *a.disable])),
        modules=modules,
    )
