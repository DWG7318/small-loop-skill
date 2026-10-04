[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageRoot,
    [Parameter(Mandatory = $true)][string]$CodexHome,
    [string]$PythonExecutable = "python",
    [string]$TestCorruptStagedRelativePath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-Within([string]$Root, [string]$Path) {
    $rootFull = (Get-FullPath $Root).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $pathFull = Get-FullPath $Path
    if (-not $pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path outside CodexHome: $pathFull"
    }
    return $pathFull
}

function Invoke-HiddenPython([string[]]$Arguments) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $PythonExecutable
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Verification failed ($($process.ExitCode)): $stdout$stderr"
    }
    return $stdout.Trim()
}

function Get-ManagedRoots([string]$Root) {
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'install-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $skills = @($manifest.files.path | Where-Object { $_ -like 'skills/*/SKILL.md' } | ForEach-Object { ($_ -split '/')[1] } | Sort-Object -Unique)
    if ($skills.Count -ne 16) { throw "Package does not enumerate exactly 16 Skill roots" }
    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($skill in $skills) { $roots.Add("skills/$skill") }
    $roots.Add('tools/slk/bin')
    $roots.Add('tools/slk/share/small-loop-skill')
    $roots.Add('tools/slk/install-manifest.json')
    return $roots.ToArray()
}

function Get-ManagedState([string]$Root, [string[]]$ManagedRoots) {
    $state = [ordered]@{}
    foreach ($relative in $ManagedRoots) {
        $target = Assert-Within $Root (Join-Path $Root $relative)
        if (Test-Path -LiteralPath $target -PathType Leaf) {
            $state[$relative] = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
        } elseif (Test-Path -LiteralPath $target -PathType Container) {
            foreach ($file in Get-ChildItem -LiteralPath $target -File -Recurse | Sort-Object FullName) {
                $key = [System.IO.Path]::GetRelativePath($Root, $file.FullName).Replace('\', '/')
                $state[$key] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
    return ($state | ConvertTo-Json -Compress)
}

$package = Get-FullPath $PackageRoot
$codexRoot = Get-FullPath $CodexHome
if (-not (Test-Path -LiteralPath $package -PathType Container)) { throw "PackageRoot is not a directory" }
[void][System.IO.Directory]::CreateDirectory($codexRoot)
$verifyScript = Join-Path $PSScriptRoot 'verify_local_install.py'
$timestamp = [DateTimeOffset]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff')
$temporaryRoot = Assert-Within $codexRoot (Join-Path $codexRoot '.tmp')
[void][System.IO.Directory]::CreateDirectory($temporaryRoot)
$stage = Assert-Within $codexRoot (Join-Path $temporaryRoot "slk-install-stage-$timestamp")
$failureReport = Assert-Within $codexRoot (Join-Path $temporaryRoot "slk-install-failed-$timestamp.json")
$managedRoots = @()
$oldState = ""
$backupRoot = ""
$mutated = $false

try {
    [void](Invoke-HiddenPython @($verifyScript, '--root', $package, '--package-mode'))
    $managedRoots = @(Get-ManagedRoots $package)
    $oldState = Get-ManagedState $codexRoot $managedRoots

    [void][System.IO.Directory]::CreateDirectory($stage)
    Copy-Item -Path (Join-Path $package '*') -Destination $stage -Recurse -Force
    [void](Invoke-HiddenPython @($verifyScript, '--root', $stage, '--package-mode'))
    $stagedManifestTarget = Assert-Within $codexRoot (Join-Path $stage 'tools/slk/install-manifest.json')
    [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $stagedManifestTarget))
    Copy-Item -LiteralPath (Join-Path $stage 'install-manifest.json') -Destination $stagedManifestTarget -Force

    if ($TestCorruptStagedRelativePath) {
        if ($env:SLK_INSTALL_TEST_MODE -ne '1') { throw "Test corruption hook is unavailable outside test mode" }
        $corrupt = Assert-Within $stage (Join-Path $stage $TestCorruptStagedRelativePath)
        if (-not (Test-Path -LiteralPath $corrupt -PathType Leaf)) { throw "Test corruption target is not a staged file" }
        [System.IO.File]::AppendAllText($corrupt, "corrupt")
    }

    $oldVersionPath = Join-Path $codexRoot 'tools/slk/share/small-loop-skill/VERSION'
    $oldVersion = if (Test-Path -LiteralPath $oldVersionPath) { (Get-Content -LiteralPath $oldVersionPath -Raw).Trim() } else { 'absent' }
    $safeOldVersion = $oldVersion -replace '[^0-9A-Za-z._-]', '_'
    $backupRoot = Assert-Within $codexRoot (Join-Path $codexRoot "tools/slk/backups/$safeOldVersion-to-4.4.0-$timestamp")
    [void][System.IO.Directory]::CreateDirectory($backupRoot)

    $mutated = $true
    foreach ($relative in $managedRoots) {
        $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
        if (Test-Path -LiteralPath $active) {
            $backup = Assert-Within $codexRoot (Join-Path $backupRoot $relative)
            [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $backup))
            Move-Item -LiteralPath $active -Destination $backup
        }
    }
    foreach ($relative in $managedRoots) {
        $source = Assert-Within $stage (Join-Path $stage $relative)
        $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
        if (-not (Test-Path -LiteralPath $source)) { throw "Staged managed root is missing: $relative" }
        [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $active))
        Move-Item -LiteralPath $source -Destination $active
    }
    [void](Invoke-HiddenPython @($verifyScript, '--root', $codexRoot))
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    [ordered]@{status='INSTALLED'; version='4.4.0'; backup_root=$backupRoot} | ConvertTo-Json -Compress
    exit 0
} catch {
    $message = $_.Exception.Message
    $rollbackVerified = $false
    $status = 'UNCHANGED'
    if ($mutated) {
        try {
            foreach ($relative in [System.Linq.Enumerable]::Reverse([string[]]$managedRoots)) {
                $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
                if (Test-Path -LiteralPath $active) { Remove-Item -LiteralPath $active -Recurse -Force }
            }
            foreach ($relative in $managedRoots) {
                $backup = Assert-Within $codexRoot (Join-Path $backupRoot $relative)
                if (Test-Path -LiteralPath $backup) {
                    $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
                    [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $active))
                    Move-Item -LiteralPath $backup -Destination $active
                }
            }
            $rollbackVerified = ((Get-ManagedState $codexRoot $managedRoots) -eq $oldState)
            $status = if ($rollbackVerified) { 'ROLLED_BACK' } else { 'ROLLBACK_FAILED' }
        } catch {
            $message = "$message; rollback error: $($_.Exception.Message)"
            $status = 'ROLLBACK_FAILED'
        }
    } else {
        $rollbackVerified = $true
    }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    [ordered]@{
        status=$status
        version='4.4.0'
        error=$message
        active_tree_verified=$rollbackVerified
        backup_root=$backupRoot
    } | ConvertTo-Json | Set-Content -LiteralPath $failureReport -Encoding UTF8
    [Console]::Error.WriteLine("SLK install failed: $message; report=$failureReport")
    exit 1
}
