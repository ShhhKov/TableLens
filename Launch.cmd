@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0runtime\windows-x64\python\python.exe" (
  echo Bundled Python is missing. Copy the entire application folder.
  pause
  exit /b 1
)
"%~dp0runtime\windows-x64\python\python.exe" -B "%~dp0editor.py" %*
if errorlevel 1 pause
