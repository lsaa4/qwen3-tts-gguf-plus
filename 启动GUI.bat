@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Qwen3-TTS GGUF

if not exist ".venv\Scripts\python.exe" (
  echo  [x] 虚拟环境还没建好。
  echo.
  echo      先双击 setup.bat 跑一遍安装。
  echo.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" install.py --check -q
if errorlevel 1 (
  echo.
  echo  [!] 上面这些项有问题，可能启动后出错。
  echo      建议先关掉窗口，跑一遍 setup.bat。
  echo.
  timeout /t 4 >nul
)

".venv\Scripts\python.exe" 52-GUI.py
if errorlevel 1 pause
