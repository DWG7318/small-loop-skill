[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OcrvRoot,
    [Parameter(Mandatory = $true)][string]$BackupRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [System.IO.Path]::GetFullPath($OcrvRoot).TrimEnd('\', '/')
$backup = [System.IO.Path]::GetFullPath($BackupRoot)
$allowed = (Join-Path $root '.slk-backups').TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $backup.StartsWith($allowed, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackupRoot must be inside the selected OCRV .slk-backups directory'
}
$receiptPath = Join-Path $backup 'receipt.json'
$cmdBackup = Join-Path $backup 'slk-checker.cmd'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or -not (Test-Path -LiteralPath $cmdBackup -PathType Leaf)) {
    throw 'OCRV recovery backup is incomplete'
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.schema_version -ne 'slk.ocrv-recovery-install/v1' -or $receipt.ocrv_root -ne $root) {
    throw 'OCRV recovery backup identity mismatch'
}
Copy-Item -LiteralPath $cmdBackup -Destination (Join-Path $root 'slk-checker.cmd') -Force
$activeRecovery = Join-Path $root 'slk_checker_recovery.py'
$recoveryBackup = Join-Path $backup 'slk_checker_recovery.py'
if ($receipt.original_recovery_existed) {
    if (-not (Test-Path -LiteralPath $recoveryBackup -PathType Leaf)) { throw 'Original recovery adapter backup is missing' }
    Copy-Item -LiteralPath $recoveryBackup -Destination $activeRecovery -Force
} elseif (Test-Path -LiteralPath $activeRecovery) {
    Remove-Item -LiteralPath $activeRecovery -Force
}
[ordered]@{status='ROLLED_BACK'; version='4.3.0'; backup_root=$backup} | ConvertTo-Json -Compress
