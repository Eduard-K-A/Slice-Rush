<#
    Builds Slice Rush into a distributable Windows folder under dist\SliceRush\.

    Usage:
        .\build.ps1              # console visible (good for debugging)
        .\build.ps1 -Windowed    # no console window (booth / release build)

    The result is dist\SliceRush\ containing SliceRush.exe plus config\ and
    assets\ as real sibling folders (the game reads/writes these at runtime,
    so they must NOT be frozen inside the exe). Zip that folder to distribute.
#>
param(
    [switch]$Windowed
)

$ErrorActionPreference = "Stop"
$py = ".\venv\Scripts\python.exe"

Write-Host "==> Cleaning previous build" -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

$pyiArgs = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--name", "SliceRush",
    "--onedir",
    "--collect-all", "mediapipe",
    "--collect-all", "cv2"
)
if ($Windowed) { $pyiArgs += "--windowed" }
$pyiArgs += "run_game.py"

Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
& $py @pyiArgs

$out = "dist\SliceRush"
Write-Host "==> Copying runtime folders next to the exe" -ForegroundColor Cyan
Copy-Item -Recurse -Force config $out\config
Copy-Item -Recurse -Force assets $out\assets

Write-Host "==> Build complete: $out\SliceRush.exe" -ForegroundColor Green
