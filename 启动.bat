@echo off
rem JiuDown Desktop 启动脚本（无控制台窗口）
cd /d "%~dp0"

if exist "runtime\python\pythonw.exe" (
    start /b "" "runtime\python\pythonw.exe" "app.py"
) else if exist "runtime\python\python.exe" (
    start /b "" "runtime\python\python.exe" "app.py"
) else if exist ".venv\Scripts\pythonw.exe" (
    start /b "" ".venv\Scripts\pythonw.exe" "app.py"
) else if exist ".venv\Scripts\python.exe" (
    start /b "" ".venv\Scripts\python.exe" "app.py"
) else (
    echo 错误: 未找到 Python 环境
    echo 请确保 runtime\python\python.exe 或 .venv\Scripts\python.exe 存在
    pause
)
