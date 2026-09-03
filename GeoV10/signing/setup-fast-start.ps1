# One-time, RUN AS ADMIN on the VM image: registers a Task Scheduler "At log on"
# task so Geo starts immediately at logon - like a VNC/proxy service - without the
# Run-key startup throttle. The app self-registers this task when it runs elevated,
# but on a standard (non-admin) run it can't, so bake this into your provisioning.
#
#   powershell -ExecutionPolicy Bypass -File setup-fast-start.ps1 -Exe "C:\Geo\app.exe"

param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [string]$TaskName = "GeoAppLogon"
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Exe)) { throw "exe not found: $Exe" }

$action    = New-ScheduledTaskAction -Execute $Exe -Argument "--autostart"
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
# Run as whoever is logged on, no elevation needed at run time
$principal = New-ScheduledTaskPrincipal -GroupId "S-1-5-32-545" -RunLevel Limited   # BUILTIN\Users

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered logon task '$TaskName' -> $Exe --autostart"
