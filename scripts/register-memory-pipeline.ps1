[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string] $Config,
    [string] $Python = (Get-Command python -ErrorAction Stop).Source,
    [string] $TaskPrefix = 'AgentReadyMemoryPipeline',
    [switch] $Uninstall
)

$ErrorActionPreference = 'Stop'
$configPath = (Resolve-Path -LiteralPath $Config).Path
$pythonPath = (Resolve-Path -LiteralPath $Python).Path
$watchTask = $TaskPrefix
$watchdogTask = "$TaskPrefix-Watchdog"

if ($Uninstall) {
    foreach ($name in @($watchTask, $watchdogTask)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            if ($PSCmdlet.ShouldProcess($name, 'Unregister scheduled task')) {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false
            }
        }
    }
    return
}

& $pythonPath -m agent_memory_pipeline --config $configPath validate
if ($LASTEXITCODE -ne 0) { throw 'Memory pipeline configuration validation failed.' }
if ($WhatIfPreference) { return }

$pythonw = Join-Path (Split-Path -Parent $pythonPath) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $pythonPath }
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$watchAction = New-ScheduledTaskAction -Execute $pythonw -Argument "-m agent_memory_pipeline --config `"$configPath`" watch"
$watchTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdogAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "-m agent_memory_pipeline --config `"$configPath`" once --reconcile"
$watchdogTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName $watchTask -Action $watchAction -Trigger $watchTrigger -Principal $principal -Settings $settings -Force | Out-Null
Register-ScheduledTask -TaskName $watchdogTask -Action $watchdogAction -Trigger $watchdogTrigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $watchTask

@{
    schema_version = 'agentready.memory_pipeline_registration.v1'
    config = $configPath
    tasks = @($watchTask, $watchdogTask)
} | ConvertTo-Json -Depth 4
