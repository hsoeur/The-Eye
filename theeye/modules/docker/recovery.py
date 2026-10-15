"""Relance de Docker Desktop (hôte local uniquement) : arrêt, arrêt de WSL, redémarrage."""
import os
from typing import Callable, Tuple

from ...core.process import Runner
from .incident import PS_UTF8, ps_error

DESKTOP_EXE = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
STOP_PS = PS_UTF8 + r"""
Get-Process 'Docker Desktop' | ForEach-Object { [void]$_.CloseMainWindow() }
$end = (Get-Date).AddSeconds(10)
while ((Get-Process 'Docker Desktop', 'com.docker.backend') -and (Get-Date) -lt $end) { Start-Sleep -Seconds 1 }
Get-Process 'Docker Desktop', 'com.docker.backend' | Stop-Process -Force
"""


class Recoverer:
    def __init__(self, runner: Runner, exe: str = DESKTOP_EXE, exists: Callable[[str], bool] = os.path.isfile):
        self.runner, self.exe, self._exists = runner, exe, exists

    def run(self) -> Tuple[bool, str]:
        """(succès du lancement, détail). Rien n'est arrêté si Docker Desktop ne peut pas être relancé."""
        if not self._exists(self.exe):
            return False, f"{self.exe} introuvable"
        notes = []
        r = self.runner.powershell(STOP_PS, 60)
        if not r.ok:
            notes.append("arrêt de Docker Desktop : " + ps_error(r, 120))
        r = self.runner.run(["wsl", "--shutdown"], 60)
        if not r.ok:
            notes.append("wsl --shutdown : " + (r.err.strip() or f"code {r.code}")[:120])
        r = self.runner.powershell(PS_UTF8 + "Start-Process -FilePath '" + self.exe.replace("'", "''") + "'", 30)
        if not r.ok:
            return False, "; ".join([*notes, "lancement impossible : " + ps_error(r, 120)])
        return True, "; ".join(notes) or "Docker Desktop relancé"
