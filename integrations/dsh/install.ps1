[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$DshRoot)
$ErrorActionPreference = 'Stop'
# This former five-file overlay cannot supply the native probe and pinned
# runtimes. Keep the old entry explicit instead of returning a broken INSTALLED
# receipt. Existing rollback receipts remain supported by rollback.ps1.
throw 'SLK_DSH_USE_BUNDLED_INSTALLER: run scripts/install_local.ps1 from the prebuilt SLK package; this legacy overlay does not install a complete DSH runtime. No files were changed.'
