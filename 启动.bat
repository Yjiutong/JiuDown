@echo off
rem JiuDown Desktop 源码启动脚本（开发模式，无需打包）
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "app.py"
