"""Collecteur Linux via le client ssh (authentification par clé)."""
import base64
import os
import re
from typing import Any, Dict

from .base import CollectError, Collector, register

SCRIPT = r"""
echo "##host"; hostname
echo "##os"; . /etc/os-release 2>/dev/null; echo "$PRETTY_NAME $(uname -r)"
echo "##uptime"; cut -d' ' -f1 /proc/uptime
echo "##cpu"; head -1 /proc/stat; sleep 1; head -1 /proc/stat
echo "##nproc"; nproc
echo "##mem"; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo "##disk"; df -P -B1 -x tmpfs -x devtmpfs -x overlay -x squashfs 2>/dev/null | tail -n +2
echo "##net"; tail -n +3 /proc/net/dev
echo "##procs"; ps -eo pid,%cpu,rss,comm --sort=-rss 2>/dev/null | head -16
echo "##count"; ps -e --no-headers | wc -l
echo "##services"; systemctl list-units --type=service --all --no-legend --no-pager --plain 2>/dev/null
echo "##ports"; ss -tlnH 2>/dev/null | awk '{print $4}'
echo "##events"; journalctl -p err -n 15 --no-pager -o short-iso 2>/dev/null
"""


def parse(txt: str) -> Dict[str, Any]:
    s, cur = {}, None
    for line in txt.splitlines():
        if line.startswith("##"):
            cur = line[2:]
            s[cur] = []
        elif cur:
            s[cur].append(line)
    g = lambda k: s.get(k, [])

    cpu = 0.0
    try:
        a = list(map(int, g("cpu")[0].split()[1:]))
        b = list(map(int, g("cpu")[1].split()[1:]))
        idle = (b[3] + b[4]) - (a[3] + a[4])
        cpu = round(100 * (1 - idle / max(1, sum(b) - sum(a))), 1)
    except (IndexError, ValueError):
        pass

    mem = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in g("mem") if ":" in l}
    disks = []
    for l in g("disk"):
        p = l.split()
        if len(p) >= 6:
            disks.append({"name": p[5], "total": float(p[1]), "free": float(p[3])})
    rx = tx = 0.0
    for l in g("net"):
        if ":" in l and not l.strip().startswith("lo:"):
            f = l.split(":")[1].split()
            rx += float(f[0])
            tx += float(f[8])
    procs = []
    for l in g("procs")[1:]:
        p = l.split(None, 3)
        if len(p) == 4:
            procs.append({"pid": int(p[0]), "name": p[3], "cpu": float(p[1]), "mem": float(p[2]) * 1024})
    services = []
    for l in g("services"):
        p = l.split(None, 4)
        if len(p) >= 4:
            services.append({"name": re.sub(r"\.service$", "", p[0]), "display": p[4] if len(p) > 4 else "",
                             "state": "failed" if p[2] == "failed" else "running" if p[3] == "running" else "stopped",
                             "start": ""})
    events = []
    for l in g("events"):
        m = re.match(r"(\S+)\s+\S+\s+([^:\s]+)(?:\[\d+\])?:\s*(.*)", l)
        if m:
            events.append({"t": m.group(1), "src": m.group(2), "msg": m.group(3)[:200]})
    ports = sorted({int(x.rsplit(":", 1)[1]) for x in g("ports") if ":" in x and x.rsplit(":", 1)[1].isdigit()})
    return {"hostname": (g("host") or [""])[0], "os": (g("os") or [""])[0],
            "uptime_s": float((g("uptime") or ["0"])[0] or 0), "cpu": cpu, "cores": int((g("nproc") or ["1"])[0] or 1),
            "mem_total": mem.get("MemTotal", 0), "mem_used": mem.get("MemTotal", 0) - mem.get("MemAvailable", 0),
            "net_rx": rx, "net_tx": tx, "disks": disks, "procs": procs, "nproc": int((g("count") or ["0"])[0] or 0),
            "services": services, "ports": ports, "events": events[::-1]}


@register
class LinuxCollector(Collector):
    kind = "linux"
    label = "Linux (SSH)"
    fields = [
        {"name": "user", "label": "Utilisateur", "type": "text", "placeholder": "défaut : root",
         "pattern": r"[\w.][\w.\-]{0,99}"},
        {"name": "key", "label": "Clé SSH privée", "type": "text", "placeholder": "chemin (optionnel)",
         "pattern": r"[^\s\-][^\r\n]{0,259}"},
    ]

    def collect(self, host: Dict[str, Any]) -> Dict[str, Any]:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new"]
        if host.get("key"):
            if not os.path.isfile(host["key"]):
                raise CollectError(
                    f'Clé SSH introuvable : « {host["key"]} ». Indiquez le chemin complet du fichier de clé privée '
                    '(ex. C:\\Users\\x\\.ssh\\id_ed25519) ou laissez le champ vide ; '
                    'l\'authentification par mot de passe n\'est pas supportée.')
            cmd += ["-i", host["key"]]
        b64 = base64.b64encode(SCRIPT.encode()).decode()
        cmd += [f'{host.get("user") or "root"}@{host["ip"]}',
                f'f=/tmp/.eye.$$; echo {b64} | base64 -d > $f; sh $f < /dev/null; rm -f $f']
        r = self.runner.run(cmd, 45, input="")
        if not r.ok and not r.out.strip():
            raise CollectError((r.err.strip() or "SSH échoué")[:300])
        return parse(r.out)
