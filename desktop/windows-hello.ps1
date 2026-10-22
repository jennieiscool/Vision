param([ValidateSet('availability','verify')][string]$Action='availability')
$ErrorActionPreference='Stop'
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null=[Windows.Security.Credentials.UI.UserConsentVerifier,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]
    $availabilityType=[Windows.Security.Credentials.UI.UserConsentVerifierAvailability,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]
    $verificationType=[Windows.Security.Credentials.UI.UserConsentVerificationResult,Windows.Security.Credentials.UI,ContentType=WindowsRuntime]
    function Wait-WinRT($Operation,$ResultType) {
        $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
        $task=$method.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
        $task.GetAwaiter().GetResult()
    }
    if($Action -eq 'availability') {
        $result=Wait-WinRT ([Windows.Security.Credentials.UI.UserConsentVerifier]::CheckAvailabilityAsync()) $availabilityType
    } else {
        $result=Wait-WinRT ([Windows.Security.Credentials.UI.UserConsentVerifier]::RequestVerificationAsync('Unlock Vision')) $verificationType
    }
    @{result=$result.ToString()} | ConvertTo-Json -Compress
} catch { @{result='Unavailable';message=$_.Exception.Message} | ConvertTo-Json -Compress }
