@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Qwen3-TTS GGUF - Export Model

echo.
echo  ==================================================
echo    Qwen3-TTS GGUF   一键导出模型
echo    官方原版 safetensors  →  model-base
echo  ==================================================
echo.

rem 导出依赖装在项目 venv 里，优先用它
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  py -3.14 -V >nul 2>&1
  if not errorlevel 1 set "PY=py -3.14"
)
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
  echo      先双击 setup.bat 把环境装好，或者手动装 Python 3.14:
  echo        https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

%PY% export_model.py %*
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
  echo  导出完成，可以双击「启动GUI.bat」了。
) else (
  echo  导出没走完，按上面的提示处理后重跑本脚本。
)
echo.
pause
exit /b %RC%
