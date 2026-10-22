$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$electron = Join-Path $PSScriptRoot 'desktop/node_modules/electron/dist/electron.exe'
if (-not (Test-Path -LiteralPath $electron)) { throw 'Run Setup.cmd before launching Vision.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run Setup.cmd before launching Vision.' }

$env:HERMES_HOME = Join-Path $PSScriptRoot 'runtime/hermes'
Start-Process -FilePath $electron -ArgumentList @((Join-Path $PSScriptRoot 'desktop')) -WorkingDirectory $PSScriptRoot
