$ErrorActionPreference = 'SilentlyContinue'
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
$st = Get-NetAdapterStatistics
$r = [ordered]@{
  hostname = $env:COMPUTERNAME
  os       = "$($os.Caption) ($($os.Version))"
  uptime_s = [double]((Get-Date) - $os.LastBootUpTime).TotalSeconds
  cpu      = [double]$cpu
  cores    = [int]$cs.NumberOfLogicalProcessors
  mem_total = [double]$os.TotalVisibleMemorySize * 1024
  mem_used  = [double]($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) * 1024
  net_rx   = [double]($st | Measure-Object ReceivedBytes -Sum).Sum
  net_tx   = [double]($st | Measure-Object SentBytes -Sum).Sum
  disks    = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object { @{ name = $_.DeviceID; total = [double]$_.Size; free = [double]$_.FreeSpace } })
  services = @(Get-CimInstance Win32_Service | ForEach-Object { @{ name = $_.Name; display = $_.DisplayName; state = $_.State.ToLower(); start = $_.StartMode.ToLower() } })
  procs    = @(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 | ForEach-Object { @{ name = $_.ProcessName; pid = $_.Id; mem = [double]$_.WorkingSet64; cpu = [double]$_.CPU } })
  nproc    = @(Get-Process).Count
  ports    = @(Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort -Unique | Sort-Object)
  events   = @(Get-WinEvent -FilterHashtable @{ LogName = 'System', 'Application'; Level = 1, 2; StartTime = (Get-Date).AddHours(-24) } -MaxEvents 15 | ForEach-Object { @{ t = $_.TimeCreated.ToString('o'); src = $_.ProviderName; msg = (("$($_.Message)") -split "`n")[0] } })
}
$r | ConvertTo-Json -Depth 5 -Compress
