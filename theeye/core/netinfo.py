"""Informations réseau de la machine hôte (interfaces IPv4, passerelle par défaut)."""
import json
import os
import re
from typing import List, Optional, Tuple

from .process import Runner

_WIN_IPS = ("Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '169.254*' -and "
            "$_.IPAddress -ne '127.0.0.1'} | Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress")


def local_networks(runner: Runner) -> Tuple[List[Tuple[str, int]], Optional[str]]:
    """Retourne ([(ip, préfixe)], passerelle par défaut)."""
    nets, gw = [], None
    if os.name == "nt":
        try:
            data = json.loads(runner.powershell(_WIN_IPS, 20).out)
            for d in data if isinstance(data, list) else [data]:
                nets.append((d["IPAddress"], int(d["PrefixLength"])))
        except (ValueError, KeyError, TypeError):
            pass
        m = re.search(r"0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)", runner.run(["route", "print", "-4", "0.0.0.0"], 10).out)
        gw = m.group(1) if m else None
    else:
        for m in re.finditer(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", runner.run(["ip", "-4", "addr"], 10).out):
            if not m.group(1).startswith("127."):
                nets.append((m.group(1), int(m.group(2))))
        m = re.search(r"default via (\S+)", runner.run(["ip", "route"], 10).out)
        gw = m.group(1) if m else None
    return nets, gw
