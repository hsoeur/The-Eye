param(
    [Parameter(Mandatory)][string]$Source,
    [string]$InstallDir = 'C:\TheEye',
    [int]$Port = 8765,
    [string]$RunAsUser = '',
    [string]$RunAsPassword = '',
    [switch]$DockerActions
)
$ErrorActionPreference = 'Stop'
$task = 'TheEye'

$py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $py -or $py -like '*\WindowsApps\*') {
    $py = Get-ChildItem 'C:\Program Files\Python3*\python.exe', 'C:\Program Files (x86)\Python3*\python.exe' -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $py) { throw "Python 3.9+ introuvable sur le serveur (installer Python pour tous les utilisateurs)." }
Write-Host "Python : $py"

Write-Host "Arrêt de l'ancienne instance"
Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*$InstallDir*eye.py*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

Write-Host "Copie des fichiers vers $InstallDir (data\ est conservé)"
New-Item -ItemType Directory -Force $InstallDir | Out-Null
robocopy $Source $InstallDir /MIR /XD data __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy a échoué ($LASTEXITCODE)" }
New-Item -ItemType Directory -Force "$InstallDir\data" | Out-Null

Write-Host "Pare-feu : TCP $Port"
if (-not (Get-NetFirewallRule -DisplayName 'The Eye' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName 'The Eye' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow | Out-Null
}

Write-Host "Tâche planifiée $task"
$taskArgs = "`"$InstallDir\eye.py`" --port $Port" + $(if ($DockerActions) { ' --docker-actions' } else { '' })
$action = New-ScheduledTaskAction -Execute $py -Argument $taskArgs -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) -StartWhenAvailable -AllowStartIfOnBatteries
if ($RunAsUser) {
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
        -User $RunAsUser -Password $RunAsPassword -RunLevel Highest -Force | Out-Null
} else {
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
}
Start-ScheduledTask -TaskName $task

Write-Host "Vérification de santé"
$ok = $false
foreach ($i in 1..20) {
    Start-Sleep 3
    try {
        $r = Invoke-WebRequest "http://localhost:$Port/api/state" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}
if (-not $ok) { throw "The Eye ne répond pas sur le port $Port après le déploiement." }
Write-Host "The Eye est en ligne : http://localhost:$Port"
