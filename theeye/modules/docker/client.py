"""Accès au CLI docker (Docker Desktop ou DOCKER_HOST distant)."""
import json
import re
from typing import Any, Dict, List

from ...core.process import NOT_FOUND, Result, Runner

PS_FORMAT = ('{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","state":"{{.State}}",'
             '"status":"{{.Status}}","ports":"{{.Ports}}","project":"{{.Label "com.docker.compose.project"}}"}')
ID_RE = re.compile(r"[0-9a-f]{12,64}")
ACTIONS = ("start", "stop", "restart")


class DockerUnavailable(Exception):
    pass


def _pct(s: str) -> float:
    try:
        return float(s.strip().rstrip("%"))
    except ValueError:
        return 0.0


def health_of(status: str) -> str:
    if "(unhealthy)" in status:
        return "unhealthy"
    if "(healthy)" in status:
        return "healthy"
    if "(health: starting)" in status:
        return "starting"
    return ""


def is_fault(c: Dict[str, Any]) -> bool:
    crashed = c["state"] in ("exited", "dead") and re.search(r"\((?!0\))\d+\)", c["status"])
    return c.get("health") == "unhealthy" or bool(crashed)


class DockerClient:
    def __init__(self, runner: Runner):
        self.runner = runner

    def _check(self, r: Result) -> Result:
        if r.code == NOT_FOUND:
            raise DockerUnavailable("CLI docker introuvable")
        if not r.ok:
            raise DockerUnavailable(r.err.strip() or "docker indisponible")
        return r

    def containers(self) -> List[Dict[str, Any]]:
        out = self._check(self.runner.run(["docker", "ps", "-a", "--format", PS_FORMAT], 20)).out
        cs = [json.loads(line) for line in out.splitlines() if line.strip()]
        stats = {}
        for line in self.runner.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"], 30).out.splitlines():
            try:
                j = json.loads(line)
                stats[j["ID"]] = j
            except (ValueError, KeyError):
                pass
        for c in cs:
            j = stats.get(c["id"], {})
            c.update(cpu=_pct(j.get("CPUPerc", "0")), mem_pct=_pct(j.get("MemPerc", "0")), mem=j.get("MemUsage", ""),
                     net=j.get("NetIO", ""), blk=j.get("BlockIO", ""), pids=j.get("PIDs", ""),
                     health=health_of(c["status"]))
            c["fault"] = is_fault(c)
        return cs

    def crashed_without_restart(self) -> List[str]:
        """Noms des containers récemment sortis en `Exited (255)` sans politique restart (jamais redémarrés d'office)."""
        r = self._check(self.runner.run(["docker", "ps", "-a", "--filter", "status=exited", "--format",
                                         "{{.ID}}\t{{.Names}}\t{{.Status}}"], 20))
        found = {}
        for line in r.out.splitlines():
            cid, _, rest = line.partition("\t")
            name, _, status = rest.partition("\t")
            if "Exited (255)" in status and re.search(r"second|minute|hour", status):
                found[cid] = name
        if not found:
            return []
        pol = self.runner.run(["docker", "inspect", "--format", "{{.Id}} {{.HostConfig.RestartPolicy.Name}}", *found], 20)
        policy = {line.split()[0][:12]: line.split()[1] if len(line.split()) > 1 else ""
                  for line in pol.out.splitlines() if line.strip()}
        return sorted(n for i, n in found.items() if policy.get(i[:12], "") in ("", "no"))

    def logs(self, cid: str, tail: int = 200) -> str:
        r = self.runner.run(["docker", "logs", "--tail", str(tail), "--timestamps", cid], 30)
        return (r.out + r.err)[-30000:]

    def action(self, cid: str, action: str) -> Result:
        return self.runner.run(["docker", action, cid], 60)
