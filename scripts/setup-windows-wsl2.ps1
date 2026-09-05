#requires -Version 5.1

[CmdletBinding()]
param(
    [ValidatePattern('^[A-Za-z0-9._ -]+$')]
    [string] $Distribution = 'Ubuntu',

    [ValidatePattern('^(?:~(?:/[A-Za-z0-9._-]+)*|/(?!mnt(?:/|$))[A-Za-z0-9._/-]+)$')]
    [string] $ProjectDirectory = '~/backtest'
)

$ErrorActionPreference = 'Stop'

if ($ProjectDirectory -match '^/mnt(?:/|$)') {
    throw 'The repository must be inside the WSL Linux filesystem, not under /mnt.'
}

$wsl = Get-Command 'wsl.exe' -ErrorAction SilentlyContinue
if ($null -eq $wsl) {
    throw 'WSL is unavailable. Install WSL2 and Ubuntu first: wsl --install -d Ubuntu'
}

& $wsl.Source --status | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw 'WSL is not ready. Install or update WSL2, reboot if requested, and retry.'
}

$wslArguments = @(
    '--distribution', $Distribution,
    '--cd', $ProjectDirectory,
    '--', 'bash', 'scripts/windows-wsl2-smoke.sh'
)
& $wsl.Source @wslArguments
if ($LASTEXITCODE -ne 0) {
    throw "The Windows/WSL2 profile smoke failed with exit code $LASTEXITCODE."
}

Write-Host 'Windows 11 / WSL2 setup and smoke completed successfully.'
