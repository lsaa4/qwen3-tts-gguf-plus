@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Qwen3-TTS GGUF - Setup

echo.
echo  ==================================================
echo    Qwen3-TTS GGUF   一键环境安装 / 体检
echo  ==================================================
echo.

set "PY="
py -3.14 -V >nul 2>&1
if not errorlevel 1 set "PY=py -3.14"
if not defined PY (
  py -3 -V >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  python -V >nul 2>&1
  if not errorlevel 1 set "PY=python"
)

if not defined PY (
  echo  [x] 没找到 Python。
  echo.
  echo      请先安装 Python 3.14:
  echo        https://www.python.org/downloads/
  echo      安装时勾选 "Add python.exe to PATH"
  echo.
  pause
  exit /b 1
)

echo  使用 Python: %PY%
echo.

%PY% install.py %*
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
  echo  环境就绪，双击「启动GUI.bat」开始使用。
) else (
  echo  仍有问题未解决，请看上面的提示。
)
echo.
pause
exit /b %RC%
