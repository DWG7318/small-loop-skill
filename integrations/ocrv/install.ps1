[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OcrvRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [System.IO.Path]::GetFullPath($OcrvRoot).TrimEnd('\', '/')
$source = [System.IO.Path]::GetFullPath($PSScriptRoot)
$adapter = Join-Path $root 'slk_checker_adapter.py'
$activeCmd = Join-Path $root 'slk-checker.cmd'
$activeRecovery = Join-Path $root 'slk_checker_recovery.py'
if (-not (Test-Path -LiteralPath $adapter -PathType Leaf) -or -not (Test-Path -LiteralPath $activeCmd -PathType Leaf)) {
    throw 'OCRV root must contain the accepted slk_checker_adapter.py and slk-checker.cmd'
}
$timestamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
$backup = Join-Path $root ".slk-backups\slk-4.2.10-transport-compat-$timestamp"
$stage = Join-Path $root ".slk-stage-4.2.10-$timestamp"
[void][System.IO.Directory]::CreateDirectory($backup)
[void][System.IO.Directory]::CreateDirectory($stage)
$hadRecovery = Test-Path -LiteralPath $activeRecovery -PathType Leaf
try {
    Copy-Item -LiteralPath $activeCmd -Destination (Join-Path $backup 'slk-checker.cmd')
    if ($hadRecovery) {
        Copy-Item -LiteralPath $activeRecovery -Destination (Join-Path $backup 'slk_checker_recovery.py')
    }
    Copy-Item -LiteralPath (Join-Path $source 'slk-checker.cmd') -Destination (Join-Path $stage 'slk-checker.cmd')
    Copy-Item -LiteralPath (Join-Path $source 'slk_checker_recovery.py') -Destination (Join-Path $stage 'slk_checker_recovery.py')
    $receipt = [ordered]@{
        schema_version = 'slk.ocrv-recovery-install/v1'
        version = '4.2.10'
        ocrv_root = $root
        original_recovery_existed = $hadRecovery
        adapter_sha256 = (Get-FileHash -LiteralPath $adapter -Algorithm SHA256).Hash.ToLowerInvariant()
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'receipt.json') -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $stage 'slk-checker.cmd') -Destination $activeCmd -Force
    Copy-Item -LiteralPath (Join-Path $stage 'slk_checker_recovery.py') -Destination $activeRecovery -Force
    foreach ($name in @('slk-checker.cmd', 'slk_checker_recovery.py')) {
        $expected = (Get-FileHash -LiteralPath (Join-Path $source $name) -Algorithm SHA256).Hash
        $actual = (Get-FileHash -LiteralPath (Join-Path $root $name) -Algorithm SHA256).Hash
        if ($expected -ne $actual) { throw "OCRV integration hash mismatch: $name" }
    }
    Remove-Item -LiteralPath $stage -Recurse -Force
    [ordered]@{status='INSTALLED'; version='4.2.10'; backup_root=$backup} | ConvertTo-Json -Compress
} catch {
    if (Test-Path -LiteralPath (Join-Path $backup 'slk-checker.cmd')) {
        Copy-Item -LiteralPath (Join-Path $backup 'slk-checker.cmd') -Destination $activeCmd -Force
    }
    if ($hadRecovery -and (Test-Path -LiteralPath (Join-Path $backup 'slk_checker_recovery.py'))) {
        Copy-Item -LiteralPath (Join-Path $backup 'slk_checker_recovery.py') -Destination $activeRecovery -Force
    } elseif (Test-Path -LiteralPath $activeRecovery) {
        Remove-Item -LiteralPath $activeRecovery -Force
    }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    throw
}
