[CmdletBinding()]
param([string]$Go = 'go', [string]$WorkRoot = (Join-Path $PSScriptRoot '.build'),
      [string]$OutputRoot = (Join-Path $PSScriptRoot 'artifacts\windows-amd64'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$output = $OutputRoot
New-Item -ItemType Directory -Force -Path $output | Out-Null
Push-Location $PSScriptRoot
try {
    & $Go test ./...
    if ($LASTEXITCODE -ne 0) { throw 'Native probe tests failed.' }
    & $Go build -trimpath -buildvcs=false -o (Join-Path $output 'slk-native-probe.exe') ./cmd/slk-native-probe
    if ($LASTEXITCODE -ne 0) { throw 'Native probe build failed.' }
} finally { Pop-Location }
$source = Join-Path $WorkRoot ('ocrv-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $source | Out-Null
Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'upstream\ocrv-fabbdb296b0d97e2140ada8d54ca7d6d6d1d7ad4.zip') -DestinationPath $source
Push-Location $source
try {
    # Without its own root, Git may find the SLK parent and silently skip every
    # patch path outside the current subdirectory while still returning zero.
    & git init --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Independent OCRV patch root failed.' }
    & git apply --check (Join-Path $PSScriptRoot 'upstream\ocrv-native-probe.patch')
    if ($LASTEXITCODE -ne 0) { throw 'Exact official OCRV source patch check failed.' }
    & git apply (Join-Path $PSScriptRoot 'upstream\ocrv-native-probe.patch')
    if ($LASTEXITCODE -ne 0) { throw 'OCRV native patch failed.' }
    if (-not (Select-String -LiteralPath 'cmd\opencodereview\main.go' -SimpleMatch 'nativeprobe.StartOCRV()' -Quiet) -or
        -not (Select-String -LiteralPath 'internal\session\persist.go' -SimpleMatch 'nativeprobe.RegisterOCRVSession(jw.sessionID, filename)' -Quiet) -or
        -not (Select-String -LiteralPath 'internal\agent\agent.go' -SimpleMatch 'a.finishSLKWholeCell(ctx, comments)' -Quiet)) {
        throw 'OCRV native hook is absent after patch; refusing an uninstrumented build.'
    }
    & $Go mod edit '-require=github.com/DWG7318/slk-native-probe@v1.0.0' ('-replace=github.com/DWG7318/slk-native-probe=' + $PSScriptRoot.Replace('\','/'))
    if ($LASTEXITCODE -ne 0) { throw 'Explicit local probe dependency failed.' }
    & $Go mod tidy
    if ($LASTEXITCODE -ne 0) { throw 'OCRV dependencies failed.' }
    & $Go test ./internal/session ./internal/agent ./internal/llmloop ./internal/mcp ./internal/llm
    if ($LASTEXITCODE -ne 0) { throw 'OCRV native lifecycle/whole-CELL regression failed.' }
    & $Go build -trimpath -buildvcs=false -ldflags '-X main.Version=1.12.13-slkprobe.1.0.2' -o (Join-Path $output 'opencodereview-1.12.13-slkprobe.1.0.2.exe') ./cmd/opencodereview
    if ($LASTEXITCODE -ne 0) { throw 'Modified OCRV build failed.' }
} finally { Pop-Location }
Write-Output ('Developer source retained at ' + $source)
