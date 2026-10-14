"""Collecteur Windows via WinRM (PowerShell Remoting) ; la machine locale est lue directement."""
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

from .base import CollectError, Collector, register

SCRIPT = Path(__file__).with_name("windows.ps1")

WRAPPER = r"""
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=[Text.Encoding]::UTF8
try {
$sb=[scriptblock]::Create((Get-Content -Raw -Encoding UTF8 $env:EYE_SCRIPT))
if($env:EYE_LOCAL -eq '1'){ & $sb }
else{
  $a=@{ComputerName=$env:EYE_IP;ScriptBlock=$sb}
  if($env:EYE_USER){
    $pw = if($env:EYE_SEC){ConvertTo-SecureString $env:EYE_SEC}else{New-Object System.Security.SecureString}
    $a.Credential=New-Object PSCredential($env:EYE_USER,$pw)
  }
  Invoke-Command @a
}
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""


def clean_error(err: str) -> str:
    if "CLIXML" in err:
        parts = re.findall(r'<S S="Error">(.*?)</S>', err, re.S)
        err = re.sub(r"_x000D__x000A_", " ", " ".join(parts))
    return re.sub(r"\s+", " ", err).strip()


@register
class WindowsCollector(Collector):
    kind = "windows"
    label = "Windows (WinRM)"
    proc_cpu_unit = "s"
    fields = [
        {"name": "user", "label": "Utilisateur", "type": "text", "placeholder": "vide = compte courant",
         "pattern": r"[\w.\-\\@]{1,100}"},
        {"name": "secret", "label": "Mot de passe", "type": "password", "secret": True},
    ]

    def protect(self, value: str) -> str:
        if os.name != "nt":
            return ""
        r = self.runner.powershell("ConvertTo-SecureString $env:EYE_PW -AsPlainText -Force | ConvertFrom-SecureString",
                                   20, {"EYE_PW": value})
        return r.out.strip()

    def collect(self, host: Dict[str, Any]) -> Dict[str, Any]:
        local = host["ip"] in self.local_ips or host["ip"] in ("127.0.0.1", "localhost")
        env = {"EYE_SCRIPT": str(SCRIPT), "EYE_IP": host["ip"], "EYE_LOCAL": "1" if local else "0",
               "EYE_USER": host.get("user", ""), "EYE_SEC": host.get("secret", "")}
        r = self.runner.powershell(WRAPPER, 90, env)
        if not r.ok or not r.out.strip():
            raise CollectError((clean_error(r.err) or "aucune réponse")[:300])
        try:
            return json.loads(r.out)
        except ValueError:
            raise CollectError("réponse PowerShell illisible")
