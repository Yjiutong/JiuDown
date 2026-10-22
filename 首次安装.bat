@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   JiuDown - first run setup
echo ============================================================
echo.

if exist "runtime\python\python.exe" (
    echo [OK] Runtime already installed.
    echo      Double-click the launcher (vbs) to start JiuDown.
    echo.
    pause
    exit /b 0
)

set "URL=https://github.com/Yjiutong/JiuDown/releases/download/runtime/runtime.zip"

echo Downloading runtime (~320 MB) from GitHub Release...
echo   %URL%
echo This may take a few minutes. Keep this window open.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; $zip=Join-Path $env:TEMP 'jiudown_runtime.zip'; Invoke-WebRequest -Uri '%URL%' -OutFile $zip -UseBasicParsing; $tmp=Join-Path $env:TEMP ('jiudown_rt_'+[guid]::NewGuid().ToString('N')); Expand-Archive -Path $zip -DestinationPath $tmp -Force; $src=Get-ChildItem $tmp -Directory | Select-Object -First 1; New-Item -ItemType Directory -Force -Path (Join-Path $PWD 'runtime') | Out-Null; Get-ChildItem $src.FullName -Force | Move-Item -Destination (Join-Path $PWD 'runtime') -Force; Remove-Item $zip,$tmp -Recurse -Force"

if exist "runtime\python\python.exe" (
    echo.
    echo [OK] Runtime installed successfully.
    echo      Double-click the launcher (vbs) to start JiuDown.
) else (
    echo.
    echo [FAILED] Could not install runtime automatically.
    echo          Check network / proxy, or download this file manually and
    echo          extract its contents into the "runtime" folder:
    echo          %URL%
)
echo.
pause
