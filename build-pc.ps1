<#
.SYNOPSIS
Compile l'appli PC Orizon X dans dist\OrizonX-PC (OrizonX.exe + ffmpeg + adb).

.PARAMETER Shortcuts
Crée aussi les raccourcis « Orizon X » dans le menu Démarrer et sur le bureau.

.EXAMPLE
.\build-pc.ps1 -Shortcuts
#>
param([switch]$Shortcuts)

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$root = $PSScriptRoot
$hostDir = Join-Path $root "host-prototype"
$venvPython = Join-Path $hostDir ".venv\Scripts\python.exe"
$out = Join-Path $root "dist\OrizonX-PC"
$staging = Join-Path $root "build\pyinstaller-dist"

if (Get-Process OrizonX -ErrorAction SilentlyContinue) {
    throw "Orizon X tourne : quitte-la (icône de notification > Quitter) avant de recompiler."
}

if (-not (Test-Path $venvPython)) {
    Write-Host "Création de l'environnement Python…"
    py -m venv (Join-Path $hostDir ".venv")
    if ($LASTEXITCODE) { throw "py -m venv a échoué" }
}
& $venvPython -m pip install --disable-pip-version-check -q -r (Join-Path $hostDir "requirements-dev.txt")
if ($LASTEXITCODE) { throw "pip install a échoué" }

Push-Location $hostDir
try {
    & $venvPython app\make_icons.py
    if ($LASTEXITCODE) { throw "génération des icônes en échec" }
    & $venvPython -m PyInstaller --noconfirm --clean --onedir --windowed --name OrizonX `
        --icon (Join-Path $hostDir "app\assets\orizonx.ico") `
        --add-data "$(Join-Path $hostDir 'app\assets');app\assets" `
        --distpath $staging `
        --workpath (Join-Path $root "build\pyinstaller-work") `
        --specpath (Join-Path $root "build") `
        (Join-Path $hostDir "orizonx_pc.py")
    if ($LASTEXITCODE) { throw "PyInstaller a échoué" }
} finally {
    Pop-Location
}

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
Move-Item (Join-Path $staging "OrizonX") $out

$toolsDir = New-Item -ItemType Directory -Force (Join-Path $out "tools")
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
Copy-Item $ffmpeg $toolsDir
$ffmpegRoot = Split-Path (Split-Path $ffmpeg)
foreach ($name in "LICENSE", "README.txt") {
    $file = Join-Path $ffmpegRoot $name
    if (Test-Path $file) { Copy-Item $file (Join-Path $toolsDir "ffmpeg-$name") }
}
$adbCommand = Get-Command adb -ErrorAction SilentlyContinue
$adbDir = if ($adbCommand) { Split-Path $adbCommand.Source } else { Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools" }
foreach ($name in "adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll") {
    Copy-Item (Join-Path $adbDir $name) $toolsDir
}
$notice = Join-Path $adbDir "NOTICE.txt"
if (Test-Path $notice) { Copy-Item $notice (Join-Path $toolsDir "adb-NOTICE.txt") }

if ($Shortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $exe = Join-Path $out "OrizonX.exe"
    foreach ($folder in [Environment]::GetFolderPath("Programs"), [Environment]::GetFolderPath("Desktop")) {
        $link = $shell.CreateShortcut((Join-Path $folder "Orizon X.lnk"))
        $link.TargetPath = $exe
        $link.WorkingDirectory = $out
        $link.IconLocation = "$exe,0"
        $link.Description = "Tablette en second écran"
        $link.Save()
    }
    Write-Host "Raccourcis créés (menu Démarrer et bureau)."
}

Write-Host "OK : $out\OrizonX.exe"
