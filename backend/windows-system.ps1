param(
    [ValidateSet('overview', 'apps', 'devices', 'drives', 'settings')]
    [string]$Area = 'overview'
)
# On-demand inventory only. This helper makes no settings changes and needs no elevation.
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
try {
    $result = switch ($Area) {
        'overview' {
            $os = Get-CimInstance Win32_OperatingSystem
            $computer = Get-CimInstance Win32_ComputerSystem
            [pscustomobject]@{
                Windows = $os.Caption
                Version = $os.Version
                Build = $os.BuildNumber
                Manufacturer = $computer.Manufacturer
                Model = $computer.Model
                MemoryBytes = $computer.TotalPhysicalMemory
                Processor = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
            }
        }
        'apps' {
            $roots = @(
                'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
                'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
            )
            $desktopApps = @(Get-ItemProperty -Path $roots -ErrorAction SilentlyContinue |
                Where-Object DisplayName | Select-Object DisplayName, DisplayVersion, Publisher, InstallLocation |
                Sort-Object DisplayName, DisplayVersion -Unique)
            $storeApps = @(Get-AppxPackage -ErrorAction SilentlyContinue | Select-Object Name, Version, Publisher, InstallLocation)
            [pscustomobject]@{ DesktopApps = $desktopApps; StoreApps = $storeApps }
        }
        'devices' {
            if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
                @(Get-PnpDevice -PresentOnly | Select-Object Class, FriendlyName, Status, InstanceId)
            } else {
                @(Get-CimInstance Win32_PnPEntity | Select-Object PNPClass, Name, Status, DeviceID)
            }
        }
        'drives' {
            @(Get-CimInstance Win32_LogicalDisk | Select-Object DeviceID, DriveType, FileSystem, VolumeName, Size, FreeSpace)
        }
        'settings' {
            [pscustomobject]@{
                SettingsApp = 'ms-settings:'
                Displays = @(Get-CimInstance Win32_VideoController | Select-Object Name, CurrentHorizontalResolution, CurrentVerticalResolution)
                AudioDevices = @(Get-CimInstance Win32_SoundDevice | Select-Object Name, Status)
                NetworkAdapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Select-Object Name, InterfaceDescription, Status, LinkSpeed)
                Theme = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -ErrorAction SilentlyContinue |
                    Select-Object AppsUseLightTheme, SystemUsesLightTheme, EnableTransparency
            }
        }
    }
    [pscustomobject]@{ Area = $Area; Data = $result } | ConvertTo-Json -Depth 8
} catch {
    [pscustomobject]@{ Area = $Area; Error = $_.Exception.Message } | ConvertTo-Json
    exit 1
}
