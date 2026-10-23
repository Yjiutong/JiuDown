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
    echo      Double-click the launcher vbs to start JiuDown.
    echo.
    pause
    exit /b 0
)

echo Installing runtime...
echo   - preferred: bundled components in build_components\ (offline, ~100 MB^)
echo   - fallback : components from GitHub Release ^(~100 MB^)
echo   - last     : full runtime.zip ^(~339 MB^)
echo   Keep this window open; it may take a few minutes.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_runtime.ps1"

if exist "runtime\python\python.exe" (
    echo.
    echo [OK] Runtime installed successfully.
    echo      Double-click the launcher vbs to start JiuDown.
) else (
    echo.
    echo [FAILED] Could not install runtime automatically.
    echo          The bundled components are missing or incomplete.
    echo          Re-clone / update the repo so that build_components\
    echo          contains the 6 component zips + manifest.json, then retry.
)
echo.
pause
