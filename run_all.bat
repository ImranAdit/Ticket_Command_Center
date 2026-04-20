@echo off
echo ==========================================
echo   Adit Ticket Command Center - Quick Start
echo ==========================================
echo.

echo [1/2] Starting FastAPI Backend on port 8000...
cd backend
start "TCC-Backend" cmd /c ".\venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"
cd ..

echo [2/2] Starting Vite Frontend on port 5173...
cd frontend
start "TCC-Frontend" cmd /c "npm.cmd run dev"
cd ..

echo.
echo Servers are launching in separate windows.
echo.
echo Dashboard: http://localhost:5173
echo Backend API: http://localhost:8000
echo.
echo Keep this window open or press any key to exit this launcher...
pause > nul
