[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,
    [string]$MigrationSourceDir,
    [Parameter(Mandatory = $true)]
    [string]$BuiltAppDir,
    [switch]$LaunchAfterInstall
)

$ErrorActionPreference = 'Stop'
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path
$BuiltAppDir = (Resolve-Path -LiteralPath $BuiltAppDir).Path
if ([string]::IsNullOrWhiteSpace($MigrationSourceDir)) { $MigrationSourceDir = $SourceDir }
$MigrationSourceDir = (Resolve-Path -LiteralPath $MigrationSourceDir).Path

$appName = 'Veltrix Trading Clock'
$programsRoot = Join-Path $env:LOCALAPPDATA 'Programs'
$installDir = Join-Path $programsRoot $appName
$dataDir = Join-Path $env:LOCALAPPDATA $appName
$exePath = Join-Path $installDir 'VeltrixTradingClock.exe'

New-Item -ItemType Directory -Force -Path $installDir, $dataDir | Out-Null

# Install program binaries separately from user data so upgrades do not erase
# API credentials, broker tick files, caches, alarm audio or configuration.
Copy-Item -Path (Join-Path $BuiltAppDir '*') -Destination $installDir -Recurse -Force

# First-install migration: copy only when the destination does not already
# exist. An existing AppData file is always preserved during later upgrades.
foreach ($name in @('config.json', 'calendar_cache.json', 'market_cache.json', 'research_cache.json', 'alarm_state.json', 'focus_goals.sqlite3', '.env', '.env.example', 'alarm.mp3')) {
    $source = Join-Path $MigrationSourceDir $name
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        $source = Join-Path $SourceDir $name
    }
    $destination = Join-Path $dataDir $name
    if ((Test-Path -LiteralPath $source -PathType Leaf) -and -not (Test-Path -LiteralPath $destination)) {
        Copy-Item -LiteralPath $source -Destination $destination
    }
}

$destinationTicks = Join-Path $dataDir 'tick_data'
New-Item -ItemType Directory -Force -Path $destinationTicks | Out-Null
foreach ($tickSourceRoot in @((Join-Path $MigrationSourceDir 'tick_data'), (Join-Path $SourceDir 'tick_data'))) {
    if (Test-Path -LiteralPath $tickSourceRoot -PathType Container) {
        # Merge tick files without overwriting a file already in AppData.
        Get-ChildItem -LiteralPath $tickSourceRoot -File -Recurse | ForEach-Object {
            $relative = $_.FullName.Substring($tickSourceRoot.Length).TrimStart('\', '/')
            $target = Join-Path $destinationTicks $relative
            $targetParent = Split-Path -Parent $target
            New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
            if (-not (Test-Path -LiteralPath $target)) {
                Copy-Item -LiteralPath $_.FullName -Destination $target
            }
        }
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $dataDir 'config.json'))) {
    throw "Default configuration was not installed in $dataDir"
}

$iconLocation = "$exePath,0"
$wsh = New-Object -ComObject WScript.Shell
$desktopPath = [Environment]::GetFolderPath('Desktop')
$desktopShortcut = $wsh.CreateShortcut((Join-Path $desktopPath "$appName.lnk"))
$desktopShortcut.TargetPath = $exePath
$desktopShortcut.WorkingDirectory = $installDir
$desktopShortcut.IconLocation = $iconLocation
$desktopShortcut.Description = 'Launch Veltrix Trading Clock'
$desktopShortcut.Save()

$startMenuPath = Join-Path ([Environment]::GetFolderPath('Programs')) $appName
New-Item -ItemType Directory -Force -Path $startMenuPath | Out-Null
$startShortcut = $wsh.CreateShortcut((Join-Path $startMenuPath "$appName.lnk"))
$startShortcut.TargetPath = $exePath
$startShortcut.WorkingDirectory = $installDir
$startShortcut.IconLocation = $iconLocation
$startShortcut.Description = 'Launch Veltrix Trading Clock'
$startShortcut.Save()

Write-Host "Installed application: $installDir"
Write-Host "User data and .env folder: $dataDir"
Write-Host 'Created Desktop and Start-menu shortcuts.'

if ($LaunchAfterInstall) {
    Start-Process -FilePath $exePath -WorkingDirectory $installDir
}
