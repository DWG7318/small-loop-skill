[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OcrvRoot,
    [Parameter(Mandatory = $true)][string]$BackupRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [System.IO.Path]::GetFullPath($OcrvRoot).TrimEnd('\', '/')
$backup = [System.IO.Path]::GetFullPath($BackupRoot).TrimEnd('\', '/')
$allowed = (Join-Path $root '.slk-backups').TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if (-not $backup.StartsWith($allowed, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackupRoot must be inside the selected OCRV .slk-backups directory'
}
$receiptPath = Join-Path $backup 'receipt.json'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    throw 'OCRV integration backup receipt is missing'
}
$receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($receipt.schema_version -ne 'slk.ocrv-install/v2' -or $receipt.version -ne '4.4.1' -or $receipt.ocrv_root -ne $root) {
    throw 'OCRV integration backup identity mismatch'
}
$names = @(
    'slk_checker_adapter.py',
    'slk-checker.cmd',
    'slk_checker_post_d1.py',
    'slk_checker_recovery.py',
    'slk-checker-capabilities.json',
    'slk-native-activity-capabilities.json'
)
foreach ($name in $names) {
    $active = Join-Path $root $name
    $saved = Join-Path $backup $name
    if ($receipt.original_existed.$name) {
        if (-not (Test-Path -LiteralPath $saved -PathType Leaf)) {
            throw "Original OCRV integration backup is missing: $name"
        }
        Copy-Item -LiteralPath $saved -Destination $active -Force
        $actual = (Get-FileHash -LiteralPath $active -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $receipt.original_sha256.$name) {
            throw "OCRV rollback hash mismatch: $name"
        }
    } elseif (Test-Path -LiteralPath $active -PathType Leaf) {
        Remove-Item -LiteralPath $active -Force
    }
}
[ordered]@{status='ROLLED_BACK'; version='4.4.1'; backup_root=$backup} | ConvertTo-Json -Compress
