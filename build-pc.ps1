<#
.SYNOPSIS
Compile l'appli PC Orizon X dans dist\OrizonX-PC (OrizonX.exe + ffmpeg + adb), puis l'installateur
dist\OrizonX-Setup.exe (installer\orizonx.iss) si Inno Setup 6 est installé.

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

# Renommer d'abord : si le dossier est verrouillé, l'ancienne version reste intacte au lieu d'être à moitié effacée.
$old = Join-Path $root "dist\OrizonX-PC.old"
if (Test-Path $old) { Remove-Item -Recurse -Force $old -ErrorAction SilentlyContinue }  # reste d'une compilation précédente
if (Test-Path $out) {
    try {
        Rename-Item $out "OrizonX-PC.old"
    } catch {
        throw "Impossible de remplacer $out (ou d'effacer $old) : ferme les fenêtres de l'Explorateur ouvertes dessus, et arrête adb s'il a été lancé depuis ce dossier (adb kill-server), puis relance la compilation."
    }
}
Move-Item (Join-Path $staging "OrizonX") $out
if (Test-Path $old) { Remove-Item -Recurse -Force $old -ErrorAction SilentlyContinue }

$toolsDir = New-Item -ItemType Directory -Force (Join-Path $out "tools")
$ffmpeg = (Get-Command ffmpeg -ErrorAction Stop).Source
Copy-Item $ffmpeg $toolsDir
# winget installe ffmpeg via un lien symbolique : la licence est à côté de la cible, pas du lien.
$item = Get-Item $ffmpeg
if ($item.LinkType) {
    $target = @($item.Target)[0]
    $ffmpeg = if ([IO.Path]::IsPathRooted($target)) { $target } else { Join-Path (Split-Path $ffmpeg) $target }
}
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

# --- Installateur (Inno Setup 6 ; pas la 7, autre gamme) ---
function Find-Iscc {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        $(if (${env:ProgramFiles(x86)}) { Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe" })
    )
    foreach ($path in $candidates) {
        if ($path -and (Test-Path $path)) { return $path }
    }
    $onPath = Get-Command ISCC -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    return $null
}

$versionFile = Join-Path $hostDir "version.py"
$versionMatch = Select-String -Path $versionFile -Pattern '^__version__\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionMatch) { throw "Version introuvable dans $versionFile" }
$version = $versionMatch.Matches[0].Groups[1].Value

$iscc = Find-Iscc
if (-not $iscc) {
    Write-Host "Inno Setup 6 introuvable : installateur non compilé (l'appli, elle, est prête)."
    Write-Host "Pour l'installer : winget install --id JRSoftware.InnoSetup -e --scope user"
    Write-Host "  (ISCC.exe attendu dans %LOCALAPPDATA%\Programs\Inno Setup 6, Program Files (x86)\Inno Setup 6, ou sur le PATH)"
    return
}
$setup = Join-Path $root "dist\OrizonX-Setup.exe"
# Sortie filtrée : on garde les avertissements et le résumé, pas la liste des fichiers compressés.
& $iscc "/DAppVersion=$version" "/DSourceDir=$out" "/O$(Join-Path $root 'dist')" "/FOrizonX-Setup" `
    (Join-Path $root "installer\orizonx.iss") |
    Where-Object { $_ -notmatch '^\s*(Compressing|Parsing|Reading|Preprocessing|Compiling|Updating|Creating|Deleting|Copyright|Portions|https://|Inno Setup 6 Command-Line)' }
if ($LASTEXITCODE) { throw "ISCC a échoué (code $LASTEXITCODE)" }
Write-Host ("OK : $setup ({0:N1} Mo, version $version)" -f ((Get-Item $setup).Length / 1MB))
