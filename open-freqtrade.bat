@echo off
REM =============================================================
REM  Open Freqtrade Dashboard in browser via SSH tunnel
REM =============================================================
echo [AI Trader] Opening Freqtrade Dashboard...
echo.
echo   If tunnel is not running, start it first:
echo     make tunnel
echo   or:
echo     pwsh -NoProfile -Command "./scripts/tunnel.ps1 -Start"
echo.
start http://localhost:8080
echo [OK] Browser opened to http://localhost:8080
echo   Username: admin
echo   Password: (see config.json or env vars)
