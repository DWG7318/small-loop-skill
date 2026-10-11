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

# PS 5.1 native invocation otherwise drops embedded quotes. Every Node child
# uses ProcessStartInfo with no shell and no window, including registration.
function ConvertTo-NativeArgument([string]$Argument) {
    return '"' + [regex]::Replace([regex]::Replace($Argument, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

if (-not $env:DEEPSEEK_API_KEY) {
    $userApiKey = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
    if ($userApiKey) { $env:DEEPSEEK_API_KEY = $userApiKey }
}

$node = Join-Path (Split-Path -Parent $PSScriptRoot) 'node\node.exe'
$publicCli = Join-Path $PSScriptRoot 'node_modules\@deepseek-ai\dsh\lib\bin.js'
$packageMetadata = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'scripts\local_package_metadata.py'
# Legacy DSH also has public bin.js; the delivered metadata identifies this layout
# even when the entire required Node root is missing.
$bundled = (Test-Path -LiteralPath $packageMetadata -PathType Leaf) -or (Test-Path -LiteralPath (Split-Path -Parent $node) -PathType Container)
if ($bundled -and -not (Test-Path -LiteralPath $node -PathType Leaf)) {
    throw "Node runtime is missing: $node"
}
if ($bundled -and -not (Test-Path -LiteralPath $publicCli -PathType Leaf)) {
    throw "DSH public CLI is missing: $publicCli"
}
$runtimeRoot = if ($env:DSH_RUNTIME_ROOT) { $env:DSH_RUNTIME_ROOT } elseif ($bundled) {
    Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'data\dsh'
} else { 'F:\DSH' }
$agentsHome = if ($env:DSH_AGENTS_HOME) { $env:DSH_AGENTS_HOME } else { Join-Path $runtimeRoot 'shared-agents' }
$instanceRoot = Join-Path $runtimeRoot (Join-Path 'runs' $InstanceId)
$dshHome = Join-Path $instanceRoot 'home'
$tempRoot = Join-Path $instanceRoot 'tmp'

foreach ($path in @($dshHome, $agentsHome, (Join-Path $agentsHome 'skills'), $tempRoot)) {
    New-Item -ItemType Directory -Force -Path $path | Out-Null
}

$settingsPath = Join-Path $dshHome 'settings.yaml'
if (-not $bundled -and -not (Test-Path -LiteralPath $settingsPath)) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'slk-template\settings.yaml') -Destination $settingsPath
}

$env:DSH_HOME = $dshHome
$env:DSH_AGENTS_HOME = $agentsHome
$env:TEMP = $tempRoot
$env:TMP = $tempRoot

# Register the native user layer for this actual home. This also covers direct
# native DSH calls using the same home, without a second per-Run --patch insert.
$probeRoot = Join-Path (Split-Path -Parent $PSScriptRoot) 'native-probe'
$probeRegister = Join-Path $probeRoot 'dsh\register.mjs'
$probeExecutable = Join-Path $probeRoot 'artifacts\windows-amd64\slk-native-probe.exe'
if (-not (Test-Path -LiteralPath $probeRegister -PathType Leaf) -or
    -not (Test-Path -LiteralPath $probeExecutable -PathType Leaf)) {
    throw 'The delivered native probe is incomplete; reinstall the current SLK package.'
}
$probeNode = if ($bundled) { $node } else { (Get-Command node.exe -CommandType Application).Source }
$registrationInfo = [System.Diagnostics.ProcessStartInfo]::new()
$registrationInfo.FileName = $probeNode
$registrationInfo.UseShellExecute = $false
$registrationInfo.CreateNoWindow = $true
$registrationInfo.RedirectStandardOutput = $true
$registrationInfo.RedirectStandardError = $true
$registrationArgs = @($probeRegister, $dshHome, $PSScriptRoot, $probeExecutable)
if ($registrationInfo.PSObject.Properties.Name -contains 'ArgumentList') {
    foreach ($argument in $registrationArgs) { [void]$registrationInfo.ArgumentList.Add($argument) }
} else {
    $registrationInfo.Arguments = (@($registrationArgs | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
}
$registration = [System.Diagnostics.Process]::Start($registrationInfo)
$registrationOutput = $registration.StandardOutput.ReadToEndAsync()
$registrationError = $registration.StandardError.ReadToEndAsync()
$registration.WaitForExit()
[void]$registrationOutput.GetAwaiter().GetResult()
[void]$registrationError.GetAwaiter().GetResult()
if ($registration.ExitCode -ne 0) { throw 'Native DSH home probe registration failed; inspect its receipt before retrying.' }
$registration.Dispose()

if ($DshArgs.Count -ge 1 -and $DshArgs.Contains('--resume')) {
    if ($DshArgs.Count -ne 5 -or $DshArgs[0] -ne '--profile' -or $DshArgs[1] -ne 'headless' -or $DshArgs[2] -ne '--resume') {
        throw 'SLK DSH continuation requires exactly --profile headless --resume <session> <task>.'
    }
    if (-not $env:SLK_DSH_SESSION_ID -or $DshArgs[3] -ne $env:SLK_DSH_SESSION_ID) {
        throw 'SLK DSH continuation Session does not match the authorized environment.'
    }
    if ($bundled) {
        $DshArgs = @('--profile', 'headless', '--session-id', $DshArgs[3], $DshArgs[4])
    } else {
        $env:SLK_DSH_CONTINUATION_TRUSTED = '1'
        $DshArgs = @('--profile', 'headless', $DshArgs[4])
    }
}

if ($env:SLK_NATIVE_ACTIVITY_PATH -or $env:SLK_NATIVE_ACTIVITY_CONTEXT) {
    if (-not $env:SLK_NATIVE_ACTIVITY_PATH -or -not $env:SLK_NATIVE_ACTIVITY_CONTEXT) {
        throw 'SLK DSH native activity binding is incomplete.'
    }
    # Exact task binding is consumed by the globally loaded single plugin.
}

if (-not $bundled) {
    & (Join-Path $PSScriptRoot 'node_modules\.bin\dsh.cmd') @DshArgs
    exit $LASTEXITCODE
}

$info = [System.Diagnostics.ProcessStartInfo]::new()
$info.FileName = $node
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$git = Join-Path (Split-Path -Parent $PSScriptRoot) 'git\cmd'
if (-not (Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue) -and
    (Test-Path -LiteralPath (Join-Path $git 'git.exe') -PathType Leaf)) {
    # Only the Node child's environment changes; an existing host Git wins.
    $info.EnvironmentVariables['PATH'] = $git + [System.IO.Path]::PathSeparator + $env:PATH
}
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$utf8 = [System.Text.UTF8Encoding]::new($false)
$info.StandardOutputEncoding = $utf8
$info.StandardErrorEncoding = $utf8
[Console]::OutputEncoding = $utf8
$nativeArgs = @($publicCli) + $DshArgs
if ($info.PSObject.Properties.Name -contains 'ArgumentList') {
    foreach ($argument in $nativeArgs) { [void]$info.ArgumentList.Add($argument) }
} else {
    $info.Arguments = (@($nativeArgs | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
}
$process = [System.Diagnostics.Process]::Start($info)
$stdout = $process.StandardOutput.ReadToEndAsync()
$stderr = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
[Console]::Out.Write($stdout.GetAwaiter().GetResult())
[Console]::Error.Write($stderr.GetAwaiter().GetResult())
exit $process.ExitCode
