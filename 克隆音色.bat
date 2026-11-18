@echo off
cd /d "%~dp0."
title 克隆音色
if "%~1"=="" (
  echo 用法：把音频文件（wav/mp3）直接拖到这个 bat 上松开
  echo 音频要求：5~15 秒、单人说话、无背景音乐
  pause
  exit /b 1
)
echo.
echo 参考音频: %~1
echo.
set /p TXT=请输入这段录音的原话（一个字都别漏，回车跳过=纯音色）: 
echo.
if "%TXT%"=="" (
  ".venv\Scripts\python.exe" clone.py "%~1"
) else (
  ".venv\Scripts\python.exe" clone.py "%~1" -t "%TXT%"
)
echo.
pause
