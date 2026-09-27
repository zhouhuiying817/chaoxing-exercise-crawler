@echo off
rem ============================================================
rem  One-click runner for the Chaoxing exercise crawler
rem  1) checks Python and dependencies
rem  2) starts crawler/main.py and waits for a URL
rem  (crawler reuses the Edge that was started in debug mode,
rem   see README section 3: start_edge_debug.bat)
rem ============================================================
cd /d "%~dp0crawler"

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found in PATH.
  echo Please install Python 3.9+ and check "Add Python to PATH".
  pause
  exit /b 1
)

python -c "import playwright, openpyxl, docx, fontTools, freetype, numpy, PIL" >nul 2>nul
if errorlevel 1 (
  echo Installing dependencies (first run, please wait)...
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Failed to install dependencies. Check your network and retry.
    pause
    exit /b 1
  )
)

python main.py
pause
