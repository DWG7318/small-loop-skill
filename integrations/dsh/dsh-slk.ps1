[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')]
    [string]$InstanceId,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DshArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $env:DEEPSEEK_API_KEY) {
    $userApiKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    if ($userApiKey) { $env:DEEPSEEK_API_KEY = $userApiKey }
}

$runtimeRoot = if ($env:DSH_RUNTIME_ROOT) { $env:DSH_RUNTIME_ROOT } else { 'F:\DSH' }
$agentsHome = if ($env:DSH_AGENTS_HOME) { $env:DSH_AGENTS_HOME } else { Join-Path $runtimeRoot 'shared-agents' }
$instanceRoot = Join-Path $runtimeRoot (Join-Path 'runs' $InstanceId)
$dshHome = Join-Path $instanceRoot 'home'
$tempRoot = Join-Path $instanceRoot 'tmp'

foreach ($path in @($dshHome, $agentsHome, (Join-Path $agentsHome 'skills'), $tempRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$settingsPath = Join-Path $dshHome 'settings.yaml'
if (-not (Test-Path -LiteralPath $settingsPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'slk-template\settings.yaml') -Destination $settingsPath
}

$env:DSH_HOME = $dshHome
$env:DSH_AGENTS_HOME = $agentsHome
$env:TEMP = $tempRoot
$env:TMP = $tempRoot

if ($DshArgs.Count -ge 1 -and $DshArgs.Contains('--resume')) {
    if ($DshArgs.Count -ne 5 -or $DshArgs[0] -ne '--profile' -or $DshArgs[1] -ne 'headless' -or $DshArgs[2] -ne '--resume') {
        throw 'SLK DSH continuation requires exactly --profile headless --resume <session> <task>.'
    }
    if (-not $env:SLK_DSH_SESSION_ID -or $DshArgs[3] -ne $env:SLK_DSH_SESSION_ID) {
        throw 'SLK DSH continuation Session does not match the authorized environment.'
    }
    $env:SLK_DSH_CONTINUATION_TRUSTED = '1'
    $DshArgs = @('--profile', 'headless', $DshArgs[4])
}

if ($env:SLK_NATIVE_ACTIVITY_PATH -or $env:SLK_NATIVE_ACTIVITY_CONTEXT) {
    if (-not $env:SLK_NATIVE_ACTIVITY_PATH -or -not $env:SLK_NATIVE_ACTIVITY_CONTEXT) {
        throw 'SLK DSH native activity binding is incomplete.'
    }
    $patchPath = Join-Path $PSScriptRoot 'slk-native-activity.patch.yml'
    if (-not (Test-Path -LiteralPath $patchPath)) { throw 'SLK DSH native activity patch is missing.' }
    $DshArgs = @('--profile', 'headless', '--patch', $patchPath) + $DshArgs[2..($DshArgs.Count - 1)]
}

& (Join-Path $PSScriptRoot 'node_modules\.bin\dsh.cmd') @DshArgs
exit $LASTEXITCODE

