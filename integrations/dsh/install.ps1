[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DshRoot)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $DshRoot).Path
$files = @('dsh-slk.ps1', 'slk-native-activity.patch.yml', 'slk_native_activity.mjs', 'slk-worker-capabilities.json')
$backup = Join-Path $root ('.slk-backups\4.4.2-' + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$original = @{}
foreach ($name in $files) {
    $source = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "DSH integration source missing: $name" }
    $target = Join-Path $root $name
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Copy-Item -LiteralPath $target -Destination (Join-Path $backup $name)
        $original[$name] = $true
    } else { $original[$name] = $false }
    Copy-Item -LiteralPath $source -Destination $target -Force
}
$receipt = @{ version = '4.4.2'; dsh_root = $root; backup_root = $backup; original = $original; installed_sha256 = @{} }
foreach ($name in $files) { $receipt.installed_sha256[$name] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $root $name)).Hash.ToLowerInvariant() }
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $backup 'receipt.json') -Encoding utf8
$receipt | ConvertTo-Json -Depth 6 -Compress
