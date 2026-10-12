<#
.SYNOPSIS
Compile l'APK Orizon X signée avec la clé de release (dist\OrizonX.apk) et affiche l'empreinte SHA-256 du certificat.

.DESCRIPTION
La clé vit hors du dépôt : %USERPROFILE%\OrizonX-signing\keystore.properties, ou le dossier ORIZONX_SIGNING_DIR.
Gradle lit ce fichier le temps du build ; ce script n'affiche jamais les mots de passe.
La version (nom et code) vient de host-prototype\version.py.
#>
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$androidDir = Join-Path $root "android"

$jbr = "C:\Program Files\Android\Android Studio\jbr"
if (-not (Test-Path (Join-Path $jbr "bin\java.exe"))) { throw "JDK d'Android Studio introuvable : $jbr" }
$env:JAVA_HOME = $jbr

Push-Location $androidDir
try {
    & .\gradlew.bat :app:assembleRelease
    if ($LASTEXITCODE) { throw "Gradle a échoué (voir ci-dessus ; clé de signature absente ?)" }
} finally {
    Pop-Location
}

$apk = Join-Path $androidDir "app\build\outputs\apk\release\app-release.apk"
if (-not (Test-Path $apk)) { throw "APK release introuvable : $apk" }
$distDir = New-Item -ItemType Directory -Force (Join-Path $root "dist")
$out = Join-Path $distDir "OrizonX.apk"
Copy-Item $apk $out -Force
Write-Host "OK : $out ($([math]::Round((Get-Item $out).Length / 1MB, 1)) Mo)"

# Empreinte du certificat (publique) : apksigner du SDK, le plus récent installé.
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } elseif ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }
$apksigner = Get-ChildItem (Join-Path $sdk "build-tools") -Directory -ErrorAction SilentlyContinue |
    Sort-Object { try { [version]$_.Name } catch { [version]"0.0" } } -Descending |
    ForEach-Object { Join-Path $_.FullName "apksigner.bat" } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1
if (-not $apksigner) {
    Write-Warning "apksigner introuvable dans $sdk\build-tools : empreinte non affichée."
    return
}
$env:JAVA_HOME = $jbr  # apksigner.bat s'appuie sur java
$report = & $apksigner verify --print-certs $out
if ($LASTEXITCODE) { throw "La signature de $out ne se vérifie pas" }
$report | Where-Object { $_ -match "certificate SHA-256 digest|Signer #1 certificate DN" } | ForEach-Object { Write-Host $_ }
