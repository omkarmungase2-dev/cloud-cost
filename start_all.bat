@echo off
rem =============================================================================
rem Cloud Cost Firewall — Windows Startup Helper
rem
rem Starts:
rem   1. Docker containers (Redis on 6379, PostgreSQL on 5432)
rem   2. Mock AI upstream server (port 9000)
rem   3. Cloud Cost Firewall proxy (port 8000)
rem   4. Opens http://localhost:8000/playground in default browser
rem
rem NOTE: For a real AI provider (Gemini, Groq, OpenAI, Ollama), configure .env
rem       and comment out / remove the Mock AI line below.
rem =============================================================================

cd /d "%~dp0"

echo [1/3] Starting Docker services (Redis + PostgreSQL)...
docker compose up -d
timeout /t 6 /nobreak >nul

echo [2/3] Starting Mock AI Server on port 9000...
start "Mock AI Server (Port 9000)" cmd /k "call .venv\Scripts\activate.bat && python tools\mock_llm.py"

echo [3/3] Starting Cloud Cost Firewall on port 8000...
start "Cost Firewall Proxy (Port 8000)" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --env-file .env --port 8000"

timeout /t 5 /nobreak >nul
echo Launching Playground UI...
start http://localhost:8000/playground

echo Done! The Cost Firewall is running.
