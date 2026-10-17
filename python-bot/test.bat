@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHONBIN=.venv\Scripts\python.exe"
) else (
  set "PYTHONBIN=python"
)

set PYTHONIOENCODING=utf-8

echo ---- EVA automated checks (pools + funnel + fuzz + diagnostics + transport) ----
echo [1/7] pool check: input triggers - output replies (renamed pools)
"%PYTHONBIN%" test_matcher.py
if errorlevel 1 (
  echo [ERROR] matcher test failed.
  pause
  exit /b 1
)
echo [2/7] funnel check: first-SMS routing - country-once - asksc - share - END
"%PYTHONBIN%" test_live.py
if errorlevel 1 (
  echo [ERROR] live chat test failed.
  pause
  exit /b 1
)
echo [3/7] fuzz check: random inputs - states stay valid, no repeats
"%PYTHONBIN%" test_fuzz.py
if errorlevel 1 (
  echo [ERROR] fuzz test failed.
  pause
  exit /b 1
)
echo [4/7] real-user demo: scripted strangers chat the full funnel to END
"%PYTHONBIN%" demo_chat.py
if errorlevel 1 (
  echo [ERROR] demo chat failed.
  pause
  exit /b 1
)
echo [5/7] debug checks: timings - tracebacks - redaction - idle polling
"%PYTHONBIN%" tests\test_smooth_debug.py
if errorlevel 1 (
  echo [ERROR] debug checks failed.
  pause
  exit /b 1
)
echo [6/7] browser API/WebSocket trace checks
"%PYTHONBIN%" tests\test_socket_trace.py
if errorlevel 1 (
  echo [ERROR] browser trace checks failed.
  pause
  exit /b 1
)
echo [7/7] browserless Socket.IO transport foundation checks
"%PYTHONBIN%" tests\test_chitchat_socket.py
if errorlevel 1 (
  echo [ERROR] Socket.IO transport checks failed.
  pause
  exit /b 1
)

echo.
echo ALL AUTOMATED CHECKS PASSED.
echo.
echo ---- EVA live chat test (RuleEngine, manual - /quit to exit) --------
"%PYTHONBIN%" tools\live_chat.py
if errorlevel 1 (
  echo [ERROR] live chat failed.
  pause
  exit /b 1
)
endlocal
