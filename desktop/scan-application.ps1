# Read file identity and run Defender without launching the selected application.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$scanPath = $env:VISION_SCAN_PATH
$result = @{ signature = 'Unknown'; publisher = ''; engine = 'Microsoft Defender'; state = 'unavailable'; detail = ''; version = ''; scanned_at = [DateTime]::UtcNow.ToString('o') }
try {
    $signature = Get-AuthenticodeSignature -LiteralPath $scanPath
    $result.signature = [string]$signature.Status
    if ($signature.SignerCertificate) { $result.publisher = [string]$signature.SignerCertificate.Subject }
} catch { $result.signature = 'Unavailable' }
try {
    $defenderState = Get-MpComputerStatus
    if (-not $defenderState.AntivirusEnabled) { throw 'Microsoft Defender antivirus is unavailable or disabled. Enable it in Windows Security to scan this app.' }
    $result.version = [string]$defenderState.AntivirusSignatureVersion
    $result.definitions_updated = [string]$defenderState.AntivirusSignatureLastUpdated
    $platform = Join-Path $env:ProgramData 'Microsoft\Windows Defender\Platform'
    $scanner = $null
    if (Test-Path -LiteralPath $platform) {
        $scanner = Get-ChildItem -LiteralPath $platform -Directory | Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'MpCmdRun.exe' } | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if (-not $scanner) { $scanner = Join-Path $env:ProgramFiles 'Windows Defender\MpCmdRun.exe' }
    if (-not (Test-Path -LiteralPath $scanner)) { throw 'Microsoft Defender scan tool could not be found.' }
    $scanOutput = & $scanner -Scan -ScanType 3 -File $scanPath -DisableRemediation 2>&1
    $scanCode = $LASTEXITCODE
    $result.code = $scanCode
    $result.detail = ($scanOutput | Out-String).Trim()
    if ($scanCode -eq 0) { $result.state = 'clear' }
    else { $result.state = 'blocked' }
} catch { $result.state = 'unavailable'; $result.detail = $_.Exception.Message }
$result | ConvertTo-Json -Compress -Depth 4
