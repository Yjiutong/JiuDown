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
echo   - preferred: components from GitHub Release ^(~100 MB total^)
echo   - fallback : full runtime.zip ^(~339 MB^)
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
    echo          Check network / proxy, or download manually from:
    echo          https://github.com/Yjiutong/JiuDown/releases/tag/runtime
    echo          and extract its contents into the "runtime" folder.
)
echo.
pause
