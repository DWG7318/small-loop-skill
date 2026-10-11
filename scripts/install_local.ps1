[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageRoot,
    [Parameter(Mandatory = $true)][string]$CodexHome,
    [string]$PythonExecutable = "",
    [string]$OcrvUserHome = "",
    [string]$DshUserHome = "",
    [string]$TestCorruptStagedRelativePath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$utf8 = [System.Text.UTF8Encoding]::new($false)
# PS5.1 CREATE_NO_WINDOW otherwise emits the locale code page, even with pipes.
[Console]::OutputEncoding = $utf8

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

function ConvertTo-NativeArgument([string]$Argument) {
    # CommandLineToArgvW/CRT quoting for .NET Framework's Arguments fallback.
    return '"' + [regex]::Replace([regex]::Replace($Argument, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Invoke-HiddenPython([string]$Root, [string[]]$Arguments) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
        $info.FileName = Join-Path $Root 'tools/slk/runtime/python/python.exe'
        if (-not (Test-Path -LiteralPath $info.FileName -PathType Leaf)) {
            throw "Python runtime is missing: $($info.FileName)"
        }
    } else {
        # Explicit development/legacy override only; default never consults PATH.
        $info.FileName = $PythonExecutable
    }
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    # The isolated embed needs a command-line UTF8 mode; explicit Python may
    # also inherit PYTHONIOENCODING, so fix that only for this child.
    $info.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $Arguments = @('-X', 'utf8') + $Arguments
    if ($info.PSObject.Properties.Name -contains 'ArgumentList') {
        foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add($argument) }
    } else {
        $info.Arguments = (@($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    }
    $process = [System.Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        throw "Verification failed ($($process.ExitCode)): $stdout$stderr"
    }
    return $stdout.Trim()
}

function Invoke-HiddenProbeRegistration([string]$Root, [string[]]$Arguments) {
    $info = [System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName = Join-Path $Root 'tools/slk/runtime/node/node.exe'
    if (-not (Test-Path -LiteralPath $info.FileName -PathType Leaf)) { throw 'Bundled Node runtime is missing' }
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = $utf8
    $info.StandardErrorEncoding = $utf8
    $Arguments = @((Join-Path $Root 'tools/slk/runtime/native-probe/dsh/register.mjs')) + $Arguments
    $info.WorkingDirectory = (Get-Location).ProviderPath
    if ($info.PSObject.Properties.Name -contains 'ArgumentList') {
        foreach ($argument in $Arguments) { [void]$info.ArgumentList.Add($argument) }
    } else {
        $info.Arguments = (@($Arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    }
    $process = [System.Diagnostics.Process]::Start($info)
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    $output = $stdout.GetAwaiter().GetResult()
    $errorOutput = $stderr.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0) {
        $failure = [System.Exception]::new("Native probe registration failed ($($process.ExitCode)): $output$errorOutput")
        try {
            $nativeFailure = $errorOutput.Trim() | ConvertFrom-Json
            if ($nativeFailure.error -eq 'SLK_NATIVE_PROBE_REGISTRATION_FAILED') {
                $failure.Data['native_probe_failure'] = $nativeFailure
            }
        } catch { } # An unparseable failure is unknown, never a rollback-success signal.
        throw $failure
    }
    return $output.Trim()
}

function Get-ManagedRoots([string]$Root) {
    $manifest = Get-Content -LiteralPath (Join-Path $Root 'install-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $skills = @($manifest.files.path | Where-Object { $_ -like 'skills/*/SKILL.md' } | ForEach-Object { ($_ -split '/')[1] } | Sort-Object -Unique)
    if ($skills.Count -ne $manifest.skill_count) { throw "Package Skill roots differ from its verified manifest" }
    $roots = [System.Collections.Generic.List[string]]::new()
    foreach ($skill in $skills) { $roots.Add("skills/$skill") }
    foreach ($document in @($manifest.files.path | Where-Object { $_ -like 'docs/*' } | Sort-Object)) {
        $roots.Add([string]$document)
    }
    $roots.Add('tools/slk/bin')
    $roots.Add('tools/slk/scripts')
    foreach ($runtime in @('python', 'node', 'dsh', 'ocrv', 'temporal', 'git', 'native-probe')) {
        $roots.Add("tools/slk/runtime/$runtime")
    }
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
                $rootPrefix = (Get-FullPath $Root).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
                $key = (Assert-Within $Root $file.FullName).Substring($rootPrefix.Length).Replace('\', '/')
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
$backedUpRoots = [System.Collections.Generic.List[string]]::new()
$installedRoots = [System.Collections.Generic.List[string]]::new()
$targetVersion = "unverified"
$configState = $null
$configStateJson = ""
$probeState = $null
$probeStateJson = ""
$probeRegistrationAttempted = $false
$selectedOcrvHome = ""
if (-not [string]::IsNullOrWhiteSpace($OcrvUserHome)) {
    if (-not [System.IO.Path]::IsPathRooted($OcrvUserHome)) { throw "OcrvUserHome must be explicitly absolute" }
    $selectedOcrvHome = Get-FullPath $OcrvUserHome
}
$selectedDshHome = ''
if (-not [string]::IsNullOrWhiteSpace($DshUserHome)) {
    if (-not [System.IO.Path]::IsPathRooted($DshUserHome)) { throw 'DshUserHome must be explicitly absolute' }
    $selectedDshHome = Get-FullPath $DshUserHome
}
$probeHomeArgument = if ($selectedDshHome) { $selectedDshHome } else { '--native-home' }

try {
    [void](Invoke-HiddenPython $package @($verifyScript, '--root', $package, '--package-mode'))
    $targetVersion = (Get-Content -LiteralPath (Join-Path $package 'install-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json).version
    $managedRoots = @(Get-ManagedRoots $package)
    $oldState = Get-ManagedState $codexRoot $managedRoots

    [void][System.IO.Directory]::CreateDirectory($stage)
    Copy-Item -Path (Join-Path $package '*') -Destination $stage -Recurse -Force
    [void](Invoke-HiddenPython $stage @($verifyScript, '--root', $stage, '--package-mode'))
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
    $backupRoot = Assert-Within $codexRoot (Join-Path $codexRoot "tools/slk/backups/$safeOldVersion-to-$targetVersion-$timestamp")
    [void][System.IO.Directory]::CreateDirectory($backupRoot)

    $mutated = $true
    foreach ($relative in $managedRoots) {
        $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
        if (Test-Path -LiteralPath $active) {
            $backup = Assert-Within $codexRoot (Join-Path $backupRoot $relative)
            [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $backup))
            Move-Item -LiteralPath $active -Destination $backup
            $backedUpRoots.Add($relative)
        }
    }
    foreach ($relative in $managedRoots) {
        $source = Assert-Within $stage (Join-Path $stage $relative)
        $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
        if (-not (Test-Path -LiteralPath $source)) { throw "Staged managed root is missing: $relative" }
        [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $active))
        # All old roots have been backed up before this phase. Include an
        # attempted destination so a partial new move can also be cleaned up.
        $installedRoots.Add($relative)
        Move-Item -LiteralPath $source -Destination $active
    }
    [void](Invoke-HiddenPython $codexRoot @($verifyScript, '--root', $codexRoot))
    $probeRegistrationAttempted = $true
    $probeStateJson = Invoke-HiddenProbeRegistration $codexRoot @($probeHomeArgument,
        (Join-Path $codexRoot 'tools/slk/runtime/dsh'),
        (Join-Path $codexRoot 'tools/slk/runtime/native-probe/artifacts/windows-amd64/slk-native-probe.exe'))
    $probeState = $probeStateJson | ConvertFrom-Json
    if ($probeState.load_state -ne 'PENDING_RELOAD' -or
        -not [System.IO.Path]::IsPathRooted($probeState.home) -or
        ($selectedDshHome -and (Get-FullPath $probeState.home) -ne $selectedDshHome)) {
        throw 'Native probe registration returned an inconsistent home/load-state receipt'
    }
    if ($selectedOcrvHome) {
        $configHelper = Join-Path $codexRoot 'tools/slk/scripts/configure_ocrv.py'
        $configStateJson = Invoke-HiddenPython $codexRoot @('-B', $configHelper,
            '--slk-root', (Join-Path $codexRoot 'tools/slk'), '--ocrv-user-home', $selectedOcrvHome,
            '--backup-root', $backupRoot)
        $configState = $configStateJson | ConvertFrom-Json
    }
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    [ordered]@{status='INSTALLED'; version=$targetVersion; backup_root=$backupRoot; dsh_probe=$probeState} | ConvertTo-Json -Compress -Depth 5
    exit 0
} catch {
    $message = $_.Exception.Message
    $probeFailure = $_.Exception.Data['native_probe_failure']
    $rollbackVerified = $false
    $status = 'UNCHANGED'
    if ($mutated) {
        try {
            $configRestored = $true
            $probeRestored = $true
            if ($probeRegistrationAttempted -and $null -eq $probeState) {
                $probeRestored = $null -ne $probeFailure -and
                    ($probeFailure.PSObject.Properties.Name -contains 'rollback_state') -and
                    $probeFailure.rollback_state -in @('UNCHANGED', 'ROLLED_BACK')
                if (-not $probeRestored) { $message = "$message; native probe registration rollback is failed or unconfirmed" }
            }
            if ($null -ne $probeState -and $probeState.changed) {
                try {
                    # Use the still-intact verified package before rolling back
                    # Node/probe runtimes; a user conflict keeps the whole home registration.
                    $restoredProbe = (Invoke-HiddenProbeRegistration $package @('rollback', $probeState.receipt)) | ConvertFrom-Json
                    if (@($restoredProbe.conflicts).Count -ne 0) { throw 'User changes conflict with the probe registration rollback' }
                } catch {
                    $probeRestored = $false
                    $message = "$message; native probe restore skipped/failed (intervening edits are retained): $($_.Exception.Message)"
                }
            }
            if ($null -ne $configState -and $configState.changed) {
                try {
                    # Restore before moving any runtime. The verified package's
                    # interpreter/helper also survives the managed-root rollback.
                    $restoreHelper = Join-Path $package 'tools/slk/scripts/configure_ocrv.py'
                    [void](Invoke-HiddenPython $package @('-B', $restoreHelper,
                        '--slk-root', (Join-Path $codexRoot 'tools/slk'), '--ocrv-user-home', $selectedOcrvHome,
                        '--backup-root', $backupRoot, '--rollback-state', $configStateJson))
                } catch {
                    $configRestored = $false
                    $message = "$message; config restore skipped/failed (intervening edits are retained)"
                }
            }
            foreach ($relative in [System.Linq.Enumerable]::Reverse([string[]]$installedRoots.ToArray())) {
                $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
                if (Test-Path -LiteralPath $active) { Remove-Item -LiteralPath $active -Recurse -Force }
            }
            foreach ($relative in $backedUpRoots) {
                $backup = Assert-Within $codexRoot (Join-Path $backupRoot $relative)
                if (Test-Path -LiteralPath $backup) {
                    $active = Assert-Within $codexRoot (Join-Path $codexRoot $relative)
                    [void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $active))
                    Move-Item -LiteralPath $backup -Destination $active
                }
            }
            $rollbackVerified = ((Get-ManagedState $codexRoot $managedRoots) -eq $oldState) -and $configRestored -and $probeRestored
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
        version=$targetVersion
        error=$message
        active_tree_verified=$rollbackVerified
        backup_root=$backupRoot
    } | ConvertTo-Json | Set-Content -LiteralPath $failureReport -Encoding UTF8
    [Console]::Error.WriteLine("SLK install failed: $message; report=$failureReport")
    exit 1
}
