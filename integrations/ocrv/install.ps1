[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OcrvRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = [System.IO.Path]::GetFullPath($OcrvRoot).TrimEnd('\', '/')
$source = [System.IO.Path]::GetFullPath($PSScriptRoot)
if (-not (Test-Path -LiteralPath $root -PathType Container)) {
    throw 'OCRV root must be an existing directory'
}
$names = @(
    'slk_checker_adapter.py',
    'slk-checker.cmd',
    'slk_checker_post_d1.py',
    'slk_checker_recovery.py',
    'slk-checker-capabilities.json',
    'slk-native-activity-capabilities.json',
    'OCRV-SLK-CONFIGURATION.md'
)
foreach ($name in $names) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $name) -PathType Leaf)) {
        throw "SLK OCRV integration source is incomplete: $name"
    }
}
$timestamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
$backup = Join-Path $root ".slk-backups\slk-4.4.2-ocrv-native-activity-$timestamp"
$stage = Join-Path $root ".slk-stage-4.4.2-$timestamp"
[void][System.IO.Directory]::CreateDirectory($backup)
[void][System.IO.Directory]::CreateDirectory($stage)
$originalExisted = [ordered]@{}
$originalSha = [ordered]@{}
$installedSha = [ordered]@{}
try {
    foreach ($name in $names) {
        $active = Join-Path $root $name
        $staged = Join-Path $stage $name
        $existed = Test-Path -LiteralPath $active -PathType Leaf
        $originalExisted[$name] = $existed
        if ($existed) {
            Copy-Item -LiteralPath $active -Destination (Join-Path $backup $name)
            $originalSha[$name] = (Get-FileHash -LiteralPath $active -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        Copy-Item -LiteralPath (Join-Path $source $name) -Destination $staged
        $installedSha[$name] = (Get-FileHash -LiteralPath $staged -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $receipt = [ordered]@{
        schema_version = 'slk.ocrv-install/v2'
        status = 'INSTALLED'
        version = '4.4.2'
        ocrv_root = $root
        backup_root = $backup
        installed_at = [DateTimeOffset]::UtcNow.ToString('o')
        original_existed = $originalExisted
        original_sha256 = $originalSha
        installed_sha256 = $installedSha
    }
    $receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $backup 'receipt.json') -Encoding UTF8
    foreach ($name in $names) {
        Copy-Item -LiteralPath (Join-Path $stage $name) -Destination (Join-Path $root $name) -Force
        $actual = (Get-FileHash -LiteralPath (Join-Path $root $name) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $installedSha[$name]) { throw "OCRV integration hash mismatch: $name" }
    }
    Remove-Item -LiteralPath $stage -Recurse -Force
    $receipt | ConvertTo-Json -Depth 8 -Compress
} catch {
    foreach ($name in $names) {
        $active = Join-Path $root $name
        $saved = Join-Path $backup $name
        if ($originalExisted[$name] -and (Test-Path -LiteralPath $saved -PathType Leaf)) {
            Copy-Item -LiteralPath $saved -Destination $active -Force
        } elseif (Test-Path -LiteralPath $active -PathType Leaf) {
            Remove-Item -LiteralPath $active -Force
        }
    }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    throw
}
