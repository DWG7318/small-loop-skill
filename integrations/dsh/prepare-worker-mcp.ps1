[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$HomePath,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$TransportPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-ExistingPath([string]$Value, [bool]$Directory) {
    if ($Value -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)') {
        throw 'PATH_MUST_BE_ABSOLUTE'
    }
    $item = Get-Item -LiteralPath $Value -Force
    if ([bool]$item.PSIsContainer -ne $Directory -or
        ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'PATH_TYPE_OR_REPARSE_INVALID'
    }
    return $item.FullName
}

function ConvertTo-NativeArgument([string]$Argument) {
    return '"' + [regex]::Replace([regex]::Replace($Argument, '(\\*)"', '$1$1\"'), '(\\+)$', '$1$1') + '"'
}

function Get-BytesSha256([byte[]]$Bytes) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash($Bytes))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}

$temporary = $null
$failureCode = 'PATH_VALIDATION'
try {
    $nativeHome = Resolve-ExistingPath $HomePath $true
    $python = Resolve-ExistingPath $PythonPath $false
    $transport = Resolve-ExistingPath $TransportPath $false
    if ([IO.Path]::GetExtension($python) -ine '.exe' -or
        [IO.Path]::GetExtension($transport) -ine '.pyz') { throw 'EXECUTABLE_OR_PACKAGE_TYPE_INVALID' }
    $patch = Resolve-ExistingPath (Join-Path $nativeHome 'cordis.patch.yml') $false

    # Use only the delivered local YAML parser. No CLI, plugin mounting, or !!js evaluation.
    $runtime = Split-Path -Parent (Split-Path -Parent $python)
    $node = Resolve-ExistingPath (Join-Path $runtime 'node\node.exe') $false
    $yamlModule = Resolve-ExistingPath (Join-Path $runtime 'dsh\node_modules\js-yaml\index.js') $false
    $failureCode = 'PATCH_ENCODING_OR_READ'
    $original = [IO.File]::ReadAllBytes($patch)
    $utf8 = [Text.UTF8Encoding]::new($false, $true)
    $text = $utf8.GetString($original)
    $newline = if ($text.Contains("`r`n")) { "`r`n" } else { "`n" }
    $commandScalar = ConvertTo-Json -InputObject $python -Compress
    $transportScalar = ConvertTo-Json -InputObject $transport -Compress
    $lines = @(
        '- insert:',
        '    - id: slk-worker-action-mcp',
        "      name: '@deepseek-ai/dsh-mcp-client'",
        '      config:',
        '        transport: stdio',
        '        serverName: slk_worker',
        ('        command: ' + $commandScalar),
        '        args:',
        "          - '-B'",
        ('          - ' + $transportScalar),
        '          - worker-action-mcp',
        '        cwd: !!js process.cwd()',
        '        failOnStartupError: true',
        '        reconnect:',
        '          enabled: false'
    )
    $prefix = if ($text.EndsWith("`n")) { '' } else { $newline }
    $addition = $prefix + ($lines -join $newline) + $newline
    $inputValue = @{
        yamlModule = $yamlModule; original = $text; addition = $addition
        command = $python; transport = $transport
    } | ConvertTo-Json -Depth 5 -Compress
    $parser = @'
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
import { isDeepStrictEqual } from 'node:util';
let status = 'INVALID_PATCH';
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const yaml = await import(pathToFileURL(input.yamlModule).href);
  const schema = yaml.DEFAULT_SCHEMA.extend([new yaml.Type('tag:yaml.org,2002:js', {
    kind: 'scalar', construct: value => ({ opaqueJS: value })
  })]);
  const original = yaml.load(input.original, { schema });
  if (!Array.isArray(original)) throw new Error();
  const desired = {
    id: 'slk-worker-action-mcp', name: '@deepseek-ai/dsh-mcp-client',
    config: {transport: 'stdio', serverName: 'slk_worker', command: input.command,
      args: ['-B', input.transport, 'worker-action-mcp'], cwd: {opaqueJS: 'process.cwd()'},
      failOnStartupError: true, reconnect: {enabled: false}}
  };
  const found = [];
  const visit = (value, active = new Set()) => {
    if (value === null || typeof value !== 'object') return;
    if (active.has(value)) throw new Error();
    active.add(value);
    if (value.id === desired.id) found.push(value);
    for (const item of Object.values(value)) visit(item, active);
    active.delete(value);
  };
  visit(original);
  if (found.length) {
    const inserted = original.some(patch => patch && !patch.id &&
      Array.isArray(patch.insert) && patch.insert.includes(found[0]));
    status = found.length === 1 && inserted && isDeepStrictEqual(found[0], desired)
      ? 'UNCHANGED' : 'MCP_ID_CONFLICT';
  } else {
    const combined = yaml.load(input.original + input.addition, { schema });
    const expected = [...original, {insert: [desired]}];
    status = isDeepStrictEqual(combined, expected) ? 'READY' : 'PATCH_NOT_APPENDABLE';
  }
} catch { /* Never publish YAML contents or parser diagnostics. */ }
process.stdout.write(JSON.stringify({status}) + '\n');
'@
    $failureCode = 'YAML_VALIDATION'
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $node
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $arguments = @('--input-type=module', '-e', $parser)
    if ($info.PSObject.Properties.Name -contains 'ArgumentList') {
        foreach ($argument in $arguments) { [void]$info.ArgumentList.Add($argument) }
    } else {
        $info.Arguments = (@($arguments | ForEach-Object { ConvertTo-NativeArgument $_ }) -join ' ')
    }
    $process = [Diagnostics.Process]::Start($info)
    try {
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $inputBytes = $utf8.GetBytes($inputValue)
        $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
        $process.StandardInput.Close()
        if (-not $process.WaitForExit(10000)) {
            $process.Kill()
            throw 'YAML_VALIDATION_TIMEOUT'
        }
        $output = $stdout.GetAwaiter().GetResult()
        [void]$stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw 'YAML_VALIDATION_FAILED' }
        $verdict = $output | ConvertFrom-Json
    } finally { $process.Dispose() }
    if ($verdict.status -eq 'UNCHANGED') {
        [pscustomobject]@{ status = 'UNCHANGED'; patch = $patch } | ConvertTo-Json -Compress
        exit 0
    }
    if ($verdict.status -ne 'READY') { throw 'PATCH_INVALID_NONAPPENDABLE_OR_MCP_ID_CONFLICT' }

    $failureCode = 'BACKUP_WRITE_OR_CONFLICT'
    $digest = Get-BytesSha256 $original
    $backup = Join-Path $nativeHome ('.slk-worker-mcp-backup-' + $digest + '.yml')
    if (Test-Path -LiteralPath $backup) {
        [void](Resolve-ExistingPath $backup $false)
        if ((Get-BytesSha256 ([IO.File]::ReadAllBytes($backup))) -ne $digest) { throw 'BACKUP_CONFLICT' }
    } else {
        $file = [IO.File]::Open($backup, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $file.Write($original, 0, $original.Length); $file.Flush($true) }
        finally { $file.Dispose() }
    }
    $failureCode = 'PATCH_ATOMIC_REPLACE'
    $temporary = Join-Path $nativeHome ('cordis.patch.yml.slk-worker-mcp.' + [guid]::NewGuid().ToString('N') + '.tmp')
    $suffix = $utf8.GetBytes($addition)
    $file = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $file.Write($original, 0, $original.Length)
        $file.Write($suffix, 0, $suffix.Length)
        $file.Flush($true)
    } finally { $file.Dispose() }
    if ((Get-BytesSha256 ([IO.File]::ReadAllBytes($patch))) -ne $digest) { throw 'PATCH_CHANGED_DURING_PREPARATION' }
    [IO.File]::Replace($temporary, $patch, [System.Management.Automation.Language.NullString]::Value)
    $temporary = $null
    [pscustomobject]@{ status = 'PREPARED'; patch = $patch; backup = $backup } | ConvertTo-Json -Compress
} catch {
    # Deliberately omit raw exceptions, parser output, and all native configuration values.
    [Console]::Error.WriteLine('WORKER_MCP_PREPARATION_FAILED: ' + $failureCode)
    exit 1
} finally {
    if ($temporary -and (Test-Path -LiteralPath $temporary)) {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}
