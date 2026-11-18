@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Qwen3-TTS API Service

if not exist ".venv\Scripts\python.exe" (
  echo  [x] 虚拟环境还没建好，先双击 setup.bat
  pause
  exit /b 1
)

echo  启动语音服务（兼容 OpenAI 的 /v1/audio/speech）
echo  默认地址 http://127.0.0.1:8899 ，Ctrl+C 退出
echo.

".venv\Scripts\python.exe" tts_server.py %*
echo.
pause
