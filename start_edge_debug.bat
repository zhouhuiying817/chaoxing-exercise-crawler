@echo off
rem ============================================================
rem  Start Edge in remote debugging mode (standalone profile)
rem  - Uses a separate profile: C:\edge-debug-profile2
rem  - Does NOT close or affect your daily Edge
rem  - Log in to Chaoxing once; session is kept afterwards
rem ============================================================

set "EDGE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=C:\Program Files\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" (
    echo [ERROR] Edge not found. Please edit EDGE path in this script.
    pause
    exit /b 1
)

rem If port 9222 is already listening, debug mode is already on.
netstat -ano | findstr ":9222" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [INFO] Port 9222 is already listening. Edge debug mode is ON.
    pause
    exit /b 0
)

echo [START] Launching Edge in debug mode (port 9222)...
start "" "%EDGE%" --remote-debugging-port=9222 --user-data-dir="C:\edge-debug-profile2" --no-first-run --remote-allow-origins=*

echo [DONE] Edge launched. Please:
echo        1. Log in to Chaoxing in the new window (once only)
echo        2. Open the target exercise page and copy the URL
echo        3. Run: python main.py  and paste the URL
pause
