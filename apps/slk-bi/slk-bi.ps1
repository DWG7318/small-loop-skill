# CLI launcher for the same GUI executable. No service, polling or method runtime.
# PowerShell otherwise does not reliably wait/capture output from Windows GUI EXEs.
$ErrorActionPreference = 'Stop'
$exe = Join-Path $PSScriptRoot 'slk-bi-desktop.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "BI executable missing: $exe" }
if ($args.Count -eq 0) {
    Start-Process -FilePath $exe -WindowStyle Hidden
    return
}
$info = [Diagnostics.ProcessStartInfo]::new()
$info.FileName = $exe
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
if ($info.PSObject.Properties.Name -contains 'ArgumentList') {
    foreach ($value in $args) { $info.ArgumentList.Add([string]$value) }
} else {
    # CommandLineToArgvW quoting, including embedded quotes and trailing slashes.
    $info.Arguments = ($args | ForEach-Object {
        '"' + [regex]::Replace([regex]::Replace([string]$_, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
    }) -join ' '
}
$process = [Diagnostics.Process]::Start($info)
$stdout = $process.StandardOutput.ReadToEndAsync()
$stderr = $process.StandardError.ReadToEndAsync()
$process.WaitForExit()
if ($stdout.Result) { Write-Output $stdout.Result.TrimEnd() }
if ($stderr.Result) { [Console]::Error.Write($stderr.Result) }
$code = $process.ExitCode
$process.Dispose()
exit $code
