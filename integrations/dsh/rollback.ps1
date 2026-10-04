[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DshRoot, [Parameter(Mandatory = $true)][string]$BackupRoot)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $DshRoot).Path
$backup = (Resolve-Path -LiteralPath $BackupRoot).Path
$receipt = Get-Content -Raw -LiteralPath (Join-Path $backup 'receipt.json') | ConvertFrom-Json
if ($receipt.dsh_root -ne $root -or $receipt.version -ne '4.4.1') { throw 'DSH rollback identity mismatch' }
foreach ($property in $receipt.original.PSObject.Properties) {
    $name = $property.Name
    $target = Join-Path $root $name
    if ($property.Value) { Copy-Item -LiteralPath (Join-Path $backup $name) -Destination $target -Force }
    else { Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue }
}
@{ status = 'rolled_back'; version = '4.4.1'; dsh_root = $root } | ConvertTo-Json -Compress
