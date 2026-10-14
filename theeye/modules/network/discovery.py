"""Sondes réseau élémentaires (ping, ARP, résolution de noms, ports)."""
import os
import re
import socket
from typing import Dict, Iterable, List, Optional, Tuple

from ...core.process import Runner

_MAC = r"[0-9a-f]{2}(?:[-:][0-9a-f]{2}){5}"


class Probes:
    def __init__(self, runner: Runner, ports: Iterable[int]):
        self.runner, self.ports = runner, sorted(ports)

    def ping(self, ip: str) -> Tuple[bool, Optional[str]]:
        cmd = ["ping", "-n", "1", "-w", "700", ip] if os.name == "nt" else ["ping", "-c", "1", "-W", "1", ip]
        out = self.runner.run(cmd, 5).out
        m = re.search(r"TTL=(\d+)", out, re.I)
        return bool(m), m.group(1) if m else None

    def arp_table(self) -> Dict[str, str]:
        res = {}
        for m in re.finditer(rf"(\d+\.\d+\.\d+\.\d+)\s+({_MAC})", self.runner.run(["arp", "-a"], 20).out, re.I):
            mac = m.group(2).upper().replace("-", ":")
            if not mac.startswith(("FF:FF", "01:00:5E")):
                res[m.group(1)] = mac
        return res

    @staticmethod
    def reverse_dns(ip: str) -> str:
        try:
            return socket.gethostbyaddr(ip)[0].split(".")[0]
        except OSError:
            return ""

    def netbios_name(self, ip: str) -> str:
        if os.name != "nt":
            return ""
        m = re.search(r"^\s*(\S+)\s+<00>\s+UNIQUE", self.runner.run(["nbtstat", "-A", ip], 4).out, re.M)
        return m.group(1) if m else ""

    @staticmethod
    def port_open(ip: str, port: int, timeout: float = 0.6) -> bool:
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except OSError:
            return False

    def open_ports(self, ip: str) -> List[int]:
        return [p for p in self.ports if self.port_open(ip, p)]
