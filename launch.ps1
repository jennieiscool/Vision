$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$visionPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $visionPython)) { throw 'Run setup.ps1 first.' }
try {
    Invoke-WebRequest -Uri 'http://127.0.0.1:8787/' -UseBasicParsing -TimeoutSec 2 | Out-Null
} catch {
    Start-Process -FilePath $visionPython -ArgumentList '-m','uvicorn','backend.server:app','--host','127.0.0.1','--port','8787','--log-level','info' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot 'runtime/server.log') -RedirectStandardError (Join-Path $PSScriptRoot 'runtime/server-error.log')
}
Start-Process 'http://127.0.0.1:8787/'
