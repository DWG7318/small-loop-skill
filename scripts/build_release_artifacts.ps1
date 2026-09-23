[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$CargoTargetDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Label)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Resolve-Tool {
    param([string]$Name, [string]$Fallback = "")
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    if ($Fallback -and (Test-Path -LiteralPath $Fallback -PathType Leaf)) {
        return $Fallback
    }
    throw "Required build tool is unavailable: $Name"
}

$repo = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) {
    if (Get-ChildItem -LiteralPath $output -Force | Select-Object -First 1) {
        throw "OutputDirectory must be absent or empty: $output"
    }
} else {
    New-Item -ItemType Directory -Path $output | Out-Null
}

$cargo = Resolve-Tool "cargo" (Join-Path $env:USERPROFILE ".cargo\bin\cargo.exe")
$pnpm = Resolve-Tool "pnpm"
$python = Resolve-Tool "python"
$env:PATH = "$(Split-Path -Parent $cargo);$env:PATH"
$biRoot = Join-Path $repo "apps\slk-bi"
if ($CargoTargetDirectory) {
    $target = [IO.Path]::GetFullPath($CargoTargetDirectory)
    $env:CARGO_TARGET_DIR = $target
} else {
    $target = Join-Path $repo "target"
}

Push-Location $repo
try {
    Invoke-Checked { & $pnpm --dir $biRoot tauri build --no-bundle } "Tauri production build"
    Invoke-Checked { & $cargo build --release -p slk-state-cli -p slk-bi-query -p slk-cargo } "Rust release build"

    foreach ($name in @("slk-bi-desktop.exe", "slk-bi-query.exe", "slk-cargo.exe", "slk-state.exe")) {
        $source = Join-Path $target "release\$name"
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Release artifact is missing: $source"
        }
        Copy-Item -LiteralPath $source -Destination (Join-Path $output $name)
    }
    Invoke-Checked { & $python scripts\build_transport_zipapp.py --output (Join-Path $output "slk-transport.pyz") } "Transport zipapp build"
    Invoke-Checked { & $python scripts\verify_bi_release.py --executable (Join-Path $output "slk-bi-desktop.exe") --fingerprint-root (Join-Path $target "release\.fingerprint") } "BI release verification"
} finally {
    Pop-Location
}

[ordered]@{
    status = "PASS"
    artifact_root = $output
    bi_build = "tauri build --no-bundle"
    headless = $true
} | ConvertTo-Json -Compress
