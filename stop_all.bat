@echo off
rem =============================================================================
rem Cloud Cost Firewall — Windows Shutdown Helper
rem Stops running Docker containers (Redis, Postgres) and closes services.
rem =============================================================================

cd /d "%~dp0"
echo Stopping Cloud Cost Firewall services...

echo [1/2] Stopping Docker containers (Redis + PostgreSQL)...
docker compose stop

echo [2/2] Terminating server processes...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :9000 ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo =============================================================================
echo All Cloud Cost Firewall services have been stopped cleanly!
echo To start again tomorrow, just double-click 'start_all.bat'.
echo =============================================================================
pause
