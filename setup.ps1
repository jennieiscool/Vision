$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments, [string]$Failure)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw $Failure }
}

function Save-Download {
    param([string]$Uri, [string]$Destination, [long]$MinimumBytes)
    if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        if ((Get-Item -LiteralPath $Destination).Length -ge $MinimumBytes) { return }
        Remove-Item -LiteralPath $Destination -Force
    }

    $partial = "$Destination.part"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    Write-Host "Downloading $(Split-Path -Leaf $Destination)..."
    Invoke-WebRequest -Uri $Uri -OutFile $partial
    if ((Get-Item -LiteralPath $partial).Length -lt $MinimumBytes) {
        Remove-Item -LiteralPath $partial -Force
        throw "The download was incomplete: $Destination"
    }
    Move-Item -LiteralPath $partial -Destination $Destination -Force
}

$node = Get-Command node.exe -ErrorAction SilentlyContinue
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $node -or -not $npm) {
    throw 'Install Node.js 24 LTS from https://nodejs.org/, then reopen Setup.cmd.'
}

$runtime = Join-Path $PSScriptRoot 'runtime'
$runtimeHermesHome = Join-Path $runtime 'hermes'
$defaultHermesHome = Join-Path $env:LOCALAPPDATA 'hermes'
$hermesHomes = @()
if ($env:HERMES_HOME) { $hermesHomes += $env:HERMES_HOME }
$hermesHomes += $runtimeHermesHome, $defaultHermesHome
$hermesHomes = @($hermesHomes | Select-Object -Unique)
New-Item -ItemType Directory -Force -Path $runtime, (Join-Path $runtime 'whisper') | Out-Null

$hermesHome = $null
$hermesRoot = $null
$hermesPython = $null
foreach ($candidateHome in $hermesHomes) {
    $candidateRoot = Join-Path $candidateHome 'hermes-agent'
    if (Test-Path -LiteralPath $candidateRoot -PathType Container) {
        $candidatePython = Join-Path $candidateRoot 'venv/Scripts/python.exe'
        if (-not (Test-Path -LiteralPath $candidatePython -PathType Leaf)) {
            throw "A Hermes installation exists at $candidateRoot but its Python environment is incomplete. Repair it using Hermes' official installer, then run setup again."
        }
        $hermesHome = $candidateHome
        $hermesRoot = $candidateRoot
        $hermesPython = $candidatePython
        Write-Host "Using existing Hermes Agent installation at $hermesRoot."
        break
    }
}

if (-not $hermesRoot) {
    $hermesHome = $runtimeHermesHome
    $hermesRoot = Join-Path $hermesHome 'hermes-agent'
    $hermesPython = Join-Path $hermesRoot 'venv/Scripts/python.exe'
    New-Item -ItemType Directory -Force -Path $hermesHome | Out-Null
    $env:HERMES_HOME = $hermesHome
    Write-Host 'Installing the official Hermes Agent runtime into runtime/hermes...'
    $installScript = Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1'
    $installer = [scriptblock]::Create($installScript.Content)
    & $installer -SkipSetup -HermesHome $hermesHome -InstallDir $hermesRoot
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { throw 'Hermes Agent installation failed.' }
}

$env:HERMES_HOME = $hermesHome
Set-Content -LiteralPath (Join-Path $runtime 'hermes-home.txt') -Value $hermesHome -NoNewline

if (-not (Test-Path -LiteralPath $hermesPython)) {
    throw "Hermes did not provide its Python environment at $hermesPython. See the official Hermes Windows install guide."
}

$uvPath = Join-Path $hermesHome 'bin/uv.exe'
if (-not (Test-Path -LiteralPath $uvPath)) {
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uvCommand) { $uvPath = $uvCommand.Source }
}
if (-not (Test-Path -LiteralPath $uvPath)) { throw 'Hermes installed, but uv.exe was not found.' }

$visionPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $visionPython)) {
    Invoke-Checked $uvPath @('venv', '--python', $hermesPython, '.venv') 'Could not create Vision Python environment.'
}
Invoke-Checked $uvPath @('pip', 'install', '--python', $visionPython, '-r', 'backend/requirements.txt') 'Vision Python dependencies could not be installed.'

$voiceRelease = 'https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0'
Save-Download "$voiceRelease/kokoro-v1.0.onnx" (Join-Path $runtime 'kokoro-v1.0.onnx') 300000000
Save-Download "$voiceRelease/voices-v1.0.bin" (Join-Path $runtime 'voices-v1.0.bin') 25000000

Write-Host 'Downloading the Faster Whisper base recognition model...'
$whisperRoot = Join-Path $runtime 'whisper'
$pythonCode = 'from faster_whisper import WhisperModel; WhisperModel("base", device="cpu", compute_type="int8", download_root=r"' + $whisperRoot + '")'
& $visionPython -c $pythonCode
if ($LASTEXITCODE -ne 0) { throw 'Faster Whisper model installation failed.' }

Invoke-Checked $npm.Source @('ci', '--prefix', (Join-Path $PSScriptRoot 'desktop')) 'Electron desktop dependencies could not be installed.'

Write-Host ''
Write-Host 'Vision setup is complete. Double-click Launch Vision.cmd to open the desktop app.' -ForegroundColor Green
