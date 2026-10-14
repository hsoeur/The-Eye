"""Exécution de commandes externes : un seul point d'entrée, jamais d'exception brute."""
import base64
import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

NOWIN = 0x08000000 if os.name == "nt" else 0
NOT_FOUND, TIMEOUT = 127, 124


@dataclass
class Result:
    code: int
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


class Runner:
    def run(self, cmd: List[str], timeout: float = 20, input: Optional[str] = None,
            env: Optional[Dict[str, str]] = None) -> Result:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input,
                               creationflags=NOWIN, encoding="utf-8", errors="replace",
                               env={**os.environ, **env} if env else None)
            return Result(r.returncode, r.stdout, r.stderr)
        except FileNotFoundError:
            return Result(NOT_FOUND, "", f"commande introuvable : {cmd[0]}")
        except subprocess.TimeoutExpired:
            return Result(TIMEOUT, "", f"délai dépassé ({timeout:.0f}s)")
        except OSError as e:
            return Result(1, "", str(e))

    def powershell(self, script: str, timeout: float = 30, env: Optional[Dict[str, str]] = None) -> Result:
        enc = base64.b64encode(script.encode("utf-16-le")).decode()
        return self.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], timeout, env=env)
