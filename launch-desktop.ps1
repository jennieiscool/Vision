$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$electron = Join-Path $PSScriptRoot 'desktop/node_modules/electron/dist/electron.exe'
if (-not (Test-Path -LiteralPath $electron)) { throw 'Run Setup.cmd before launching Vision.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run Setup.cmd before launching Vision.' }

$runtimeHermesHome = Join-Path $PSScriptRoot 'runtime/hermes'
$defaultHermesHome = Join-Path $env:LOCALAPPDATA 'hermes'
$hermesHomes = @()
if ($env:HERMES_HOME) { $hermesHomes += $env:HERMES_HOME }
$savedHermesHomeFile = Join-Path $PSScriptRoot 'runtime/hermes-home.txt'
if (Test-Path -LiteralPath $savedHermesHomeFile -PathType Leaf) {
    $savedHermesHome = (Get-Content -LiteralPath $savedHermesHomeFile -Raw).Trim()
    if ($savedHermesHome) { $hermesHomes += $savedHermesHome }
}
$hermesHomes += $runtimeHermesHome, $defaultHermesHome
$hermesHomes = @($hermesHomes | Select-Object -Unique)
$hermesHome = $null
foreach ($candidateHome in $hermesHomes) {
    if (Test-Path -LiteralPath (Join-Path $candidateHome 'hermes-agent/venv/Scripts/python.exe') -PathType Leaf) {
        $hermesHome = $candidateHome
        break
    }
}
if (-not $hermesHome) { throw 'Hermes Agent is missing. Run Setup.cmd before launching Vision.' }
$env:HERMES_HOME = $hermesHome
Start-Process -FilePath $electron -ArgumentList @((Join-Path $PSScriptRoot 'desktop')) -WorkingDirectory $PSScriptRoot
