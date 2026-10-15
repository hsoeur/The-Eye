"""Capture des preuves d'un gel du moteur Docker, avant toute relance.

Ne lève jamais : chaque étape est isolée et son résultat consigné dans summary.json.
"""
import json
import os
import platform
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ...core.process import Runner

INCIDENT_RE = re.compile(r"docker-\d{8}-\d{6}(-\d+)?")
MAX_FILE_BYTES = 10 * 1024 * 1024       # on ne garde que la fin des gros journaux
MAX_LOGS_BYTES = 100 * 1024 * 1024      # budget total des journaux copiés
MAX_LOG_FILES = 200
MAX_TEXT_BYTES = 5 * 1024 * 1024
DOCKER_BUDGET_S = 20.0
DOCKER_CMD_TIMEOUT_S = 7.0
PS_UTF8 = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$ErrorActionPreference = 'SilentlyContinue'\n"
           "$ProgressPreference = 'SilentlyContinue'\n")
CLIXML_ERR_RE = re.compile(r'<S S="Error">(.*?)</S>', re.S)


def ps_error(r: Any, limit: int = 200) -> str:
    """Message d'erreur lisible d'un résultat PowerShell (le flux CLIXML de progression est écarté)."""
    text = (r.err or "").strip()
    if text.startswith("#< CLIXML"):
        text = " ".join(m.replace("_x000D__x000A_", " ") for m in CLIXML_ERR_RE.findall(text)).strip()
    return " ".join((text or (r.out or "").strip()).split())[:limit] or f"code {r.code}"

EVENTS_PS = PS_UTF8 + r"""
$since = (Get-Date).AddHours(-3)
Get-WinEvent -FilterHashtable @{LogName='System','Application'; Level=1,2,3,4; StartTime=$since} -MaxEvents 3000 |
  Select-Object @{n='Time';e={$_.TimeCreated.ToString('s')}}, LogName, Id, LevelDisplayName, ProviderName,
    @{n='Message';e={ $m = "$($_.Message)" -replace '\s+',' '; if ($m.Length -gt 400) { $m.Substring(0,400) } else { $m } }} |
  ConvertTo-Csv -NoTypeInformation
"""
MEMORY_PS = PS_UTF8 + r"""
$os = Get-CimInstance Win32_OperatingSystem
"RAM totale (Mo) : " + [int]($os.TotalVisibleMemorySize / 1024)
"RAM libre (Mo)  : " + [int]($os.FreePhysicalMemory / 1024)
"Mémoire virtuelle libre (Mo) : " + [int]($os.FreeVirtualMemory / 1024)
"""
PROCESSES_PS = PS_UTF8 + r"""
Get-Process | Where-Object { $_.Name -like 'vmmem*' -or $_.Name -like 'com.docker*' -or $_.Name -like 'Docker Desktop*' -or $_.Name -like 'wsl*' } |
  Select-Object Name, Id, @{n='WorkingSet_Mo';e={[int]($_.WorkingSet64 / 1MB)}}, @{n='Prive_Mo';e={[int]($_.PrivateMemorySize64 / 1MB)}},
    @{n='Threads';e={$_.Threads.Count}} | Format-Table -AutoSize | Out-String -Width 200
"""


def _clean(text: str) -> str:
    return text.replace("\x00", "").strip()


class IncidentCapture:
    def __init__(self, runner: Runner, root: Path, max_incidents: int = 10, clock: Callable[[], float] = time.time,
                 timer: Callable[[], float] = time.monotonic, environ: Optional[Mapping[str, str]] = None):
        self.runner, self.root, self.max_incidents = runner, Path(root), max_incidents
        self._clock, self._timer = clock, timer
        self.environ = os.environ if environ is None else environ

    # --- point d'entrée -------------------------------------------------------------------------------------------
    def capture(self, reason: str, state: str, history: List[Any], versions: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        now = self._clock()
        summary: Dict[str, Any] = {"time": now, "time_iso": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
                                   "state": state, "reason": reason, "path": "", "steps": {}}
        try:
            dest = self._new_dir(now)
            summary["path"] = str(dest)
        except Exception as e:
            summary["error"] = f"dossier d'incident impossible : {e}"[:300]
            return summary
        steps = summary["steps"]
        self._step(steps, "journaux", lambda: self._copy_logs(dest))
        self._step(steps, "evenements", lambda: self._events(dest))
        self._step(steps, "systeme", lambda: self._system(dest))
        self._step(steps, "docker", lambda: self._docker(dest))
        self._step(steps, "historique_sonde", lambda: self._write(dest / "probe-history.json",
                                                                  json.dumps(history, ensure_ascii=False)))
        self._step(steps, "versions", lambda: self._versions(summary, versions or {}))
        self._step(steps, "retention", self._prune)
        self._step(steps, "resume", lambda: self._write(dest / "summary.json",
                                                        json.dumps(summary, indent=1, ensure_ascii=False)))
        return summary

    def _step(self, steps: Dict[str, Any], name: str, fn: Callable[[], Any]) -> None:
        try:
            steps[name] = {"ok": True, "detail": str(fn() or "")}
        except Exception as e:
            steps[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}

    def _new_dir(self, now: float) -> Path:
        base = "docker-" + time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        self.root.mkdir(parents=True, exist_ok=True)
        for n in range(1, 100):
            dest = self.root / (base if n == 1 else f"{base}-{n}")
            try:
                dest.mkdir()
                return dest
            except FileExistsError:
                continue
        raise OSError("trop d'incidents dans la même seconde")

    @staticmethod
    def _write(path: Path, text: str) -> str:
        data = text.encode("utf-8", "replace")[:MAX_TEXT_BYTES]
        path.write_bytes(data)
        return f"{len(data)} octets"

    # --- journaux -------------------------------------------------------------------------------------------------
    def _log_sources(self) -> List[Tuple[str, Path]]:
        local = self.environ.get("LOCALAPPDATA")
        sources = [("docker-desktop", Path(local) / "Docker" / "log")] if local else []
        if not any(p.is_dir() for _, p in sources) and os.name == "nt":
            users = Path(self.environ.get("SystemDrive", "C:") + "\\Users")
            try:
                sources = [("docker-desktop-" + p.parts[2], p) for p in users.glob("*/AppData/Local/Docker/log")]
            except OSError:
                pass
        program_data = self.environ.get("ProgramData", r"C:\ProgramData")
        sources.append(("programdata", Path(program_data) / "DockerDesktop"))
        return [(label, p) for label, p in sources if p.is_dir()]

    def _copy_logs(self, dest: Path) -> str:
        copied = skipped = total = 0
        for label, src in self._log_sources():
            files: List[Tuple[float, Path]] = []
            for p in src.rglob("*.log"):
                try:
                    files.append((p.stat().st_mtime, p))
                except OSError:
                    skipped += 1
            for _, p in sorted(files, key=lambda f: f[0], reverse=True):
                if copied >= MAX_LOG_FILES or total >= MAX_LOGS_BYTES:
                    skipped += 1
                    continue
                try:
                    target = dest / "logs" / label / p.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with open(p, "rb") as f:
                        size = os.fstat(f.fileno()).st_size
                        if size > MAX_FILE_BYTES:
                            f.seek(size - MAX_FILE_BYTES)
                        data = f.read(MAX_FILE_BYTES)
                    target.write_bytes(data)
                    copied += 1
                    total += len(data)
                except OSError:
                    skipped += 1
        return f"{copied} fichier(s) copié(s), {skipped} ignoré(s) (verrouillés ou hors budget)"

    # --- événements Windows ---------------------------------------------------------------------------------------
    def _events(self, dest: Path) -> str:
        if os.name != "nt":
            return "ignoré (hors Windows)"
        r = self.runner.powershell(EVENTS_PS, 90)
        if not r.ok and not r.out.lstrip().startswith('"Time"'):
            raise RuntimeError(ps_error(r))
        return self._write(dest / "events.csv", r.out)

    # --- système --------------------------------------------------------------------------------------------------
    def _system(self, dest: Path) -> str:
        parts: List[str] = []
        failed: List[str] = []

        def section(title: str, fn: Callable[[], str]) -> None:
            try:
                parts.append(f"== {title} ==\n{fn().strip() or '(vide)'}\n")
            except Exception as e:
                failed.append(title)
                parts.append(f"== {title} ==\n(échec : {e})\n")

        def ps(script: str, timeout: float = 30) -> str:
            if os.name != "nt":
                return "(ignoré : hors Windows)"
            r = self.runner.powershell(script, timeout)
            if not r.ok:
                raise RuntimeError(ps_error(r))
            return r.out

        def wsl() -> str:
            r = self.runner.run(["wsl", "-l", "-v"], 15)
            if not r.ok:
                raise RuntimeError((r.err or "wsl indisponible").strip()[:200])
            return _clean(r.out)

        def disk() -> str:
            root = self.environ.get("SystemDrive", "C:") + "\\"
            u = shutil.disk_usage(root)
            return f"{root} total {u.total // 2**20} Mo, libre {u.free // 2**20} Mo ({u.free * 100 // max(1, u.total)} %)"

        def wslconfig() -> str:
            home = self.environ.get("USERPROFILE")
            p = Path(home) / ".wslconfig" if home else None
            return p.read_text(encoding="utf-8", errors="replace")[:20000] if p and p.is_file() else "(absent)"

        section("Mémoire", lambda: ps(MEMORY_PS))
        section("Processus vmmem / com.docker / Docker Desktop / wsl", lambda: ps(PROCESSES_PS))
        section("Disque système", disk)
        section("Fichiers VHDX Docker", self._vhdx)
        section(".wslconfig", wslconfig)
        section("wsl -l -v", wsl)
        self._write(dest / "system.txt", "\n".join(parts))
        return "échecs : " + ", ".join(failed) if failed else "complet"

    def _vhdx(self) -> str:
        roots = [Path(self.environ.get("ProgramData", r"C:\ProgramData")) / "DockerDesktop"]
        if self.environ.get("LOCALAPPDATA"):
            roots.append(Path(self.environ["LOCALAPPDATA"]) / "Docker")
        lines = []
        for root in roots:
            if root.is_dir():
                for p in root.rglob("*.vhdx"):
                    try:
                        lines.append(f"{p}  {p.stat().st_size // 2**20} Mo")
                    except OSError as e:
                        lines.append(f"{p}  (illisible : {e})")
        return "\n".join(lines) or "(aucun)"

    # --- commandes docker -----------------------------------------------------------------------------------------
    def _docker(self, dest: Path) -> str:
        start, out, done = self._timer(), [], 0
        for title, cmd in (("docker info", ["docker", "info"]), ("docker ps -a", ["docker", "ps", "-a"]),
                           ("docker system df", ["docker", "system", "df"])):
            left = DOCKER_BUDGET_S - (self._timer() - start)
            if left <= 0.5:
                out.append(f"== {title} ==\n(ignoré : budget de {DOCKER_BUDGET_S:.0f} s épuisé)\n")
                continue
            r = self.runner.run(cmd, min(DOCKER_CMD_TIMEOUT_S, left))
            done += r.ok
            out.append(f"== {title} == (code {r.code})\n{(r.out + r.err).strip()[:50000]}\n")
        self._write(dest / "docker.txt", "\n".join(out))
        return f"{done}/3 commande(s) abouties"

    def _versions(self, summary: Dict[str, Any], known: Dict[str, str]) -> str:
        v = dict(known)
        r = self.runner.run(["docker", "--version"], 5)
        v["docker_cli"] = r.out.strip() if r.ok else "indisponible"
        v["python"], v["os"] = platform.python_version(), platform.platform()
        summary["versions"] = v
        return ""

    # --- rétention ------------------------------------------------------------------------------------------------
    def _incident_dirs(self) -> List[Path]:
        try:
            return sorted((p for p in self.root.iterdir() if p.is_dir() and not p.is_symlink()
                           and INCIDENT_RE.fullmatch(p.name)), key=lambda p: p.name)
        except OSError:
            return []

    def _prune(self) -> str:
        old = self._incident_dirs()[:-self.max_incidents]
        for p in old:
            shutil.rmtree(p, ignore_errors=True)
        return f"{len(old)} ancien(s) incident(s) supprimé(s)"

    def list_incidents(self, limit: int = 10) -> List[Dict[str, Any]]:
        out = []
        for p in reversed(self._incident_dirs()[-limit:]):
            try:
                s = json.loads((p / "summary.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                s = {}
            out.append({"name": p.name, "path": str(p), "time": s.get("time", 0), "reason": s.get("reason", ""),
                        "state": s.get("state", ""),
                        "failed_steps": [k for k, v in (s.get("steps") or {}).items() if not v.get("ok")]})
        return out
