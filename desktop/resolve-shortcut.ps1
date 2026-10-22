# Read a Windows application shortcut without executing or modifying it.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$shortcutPath = $env:VISION_SHORTCUT_PATH
if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) { throw 'This shortcut no longer exists.' }
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$target = [Environment]::ExpandEnvironmentVariables([string]$shortcut.TargetPath)
if (-not $target) { throw 'This shortcut does not contain a directly accessible application target.' }
@{target=$target; arguments=[string]$shortcut.Arguments; directory=[Environment]::ExpandEnvironmentVariables([string]$shortcut.WorkingDirectory)} | ConvertTo-Json -Compress
