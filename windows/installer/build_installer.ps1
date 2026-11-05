# Prismateams Automated Build & Packaging Script

param(
    [string]$Configuration = "Release",
    [string]$Platform = "x64"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$WindowsDir = Resolve-Path "$ScriptDir\.."

Write-Host "=== Prismateams Windows Build & Packaging ===" -ForegroundColor Cyan
Write-Host "Verzeichnis: $WindowsDir"

# 1. Locate MSBuild
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = $null

if (Test-Path $vswhere) {
    $installPath = & $vswhere -latest -products * -property installationPath
    if ($installPath -and (Test-Path "$installPath\MSBuild\Current\Bin\MSBuild.exe")) {
        $msbuild = "$installPath\MSBuild\Current\Bin\MSBuild.exe"
    }
}

if (-not $msbuild) {
    # Check fallback paths
    $possibleMsBuild = @(
        "C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Professional\MSBuild\Current\Bin\MSBuild.exe",
        "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\MSBuild\Current\Bin\MSBuild.exe"
    )
    foreach ($candidate in $possibleMsBuild) {
        if (Test-Path $candidate) {
            $msbuild = $candidate
            break
        }
    }
}

if ($msbuild) {
    Write-Host "Gefundenes MSBuild: $msbuild" -ForegroundColor Green
    Write-Host "Kompiliere Prismateams ($Configuration|$Platform)..." -ForegroundColor Yellow

    & $msbuild "$WindowsDir\Prismateams.vcxproj" /p:Configuration=$Configuration /p:Platform=$Platform /m
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build fehlgeschlagen mit Exit-Code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    Write-Host "Build erfolgreich!" -ForegroundColor Green
} else {
    Write-Warning "MSBuild.exe konnte nicht automatisch gefunden werden. Bitte in Visual Studio öffnen oder MSBuild-Pfad angeben."
}

# 2. Check for Inno Setup (ISCC.exe)
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $possibleIscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($cand in $possibleIscc) {
        if (Test-Path $cand) {
            $iscc = $cand
            break
        }
    }
}

if ($iscc) {
    Write-Host "Erstelle Installer mit Inno Setup ($iscc)..." -ForegroundColor Cyan
    $issFile = "$ScriptDir\PrismateamsSetup.iss"
    & $iscc $issFile
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Installer erfolgreich erstellt in windows\bin\Installer!" -ForegroundColor Green
    } else {
        Write-Warning "Inno Setup Build fehlgeschlagen."
    }
} else {
    Write-Host "Hinweis: Inno Setup (ISCC.exe) nicht im Standardpfad gefunden." -ForegroundColor Yellow
    Write-Host "Um die Installations-EXE zu generieren, installieren Sie Inno Setup 6 (z. B. via 'winget install JRSoftware.InnoSetup') und führen Sie dieses Skript erneut aus." -ForegroundColor Yellow
}

Write-Host "=== Fertig ===" -ForegroundColor Cyan
