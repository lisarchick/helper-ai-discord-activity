@echo off
chcp 65001 >nul
REM === Alisa AI Activity frontend (dev server на http://127.0.0.1:5173) ===
cd /d "%~dp0"

if not exist "node_modules" (
    echo [*] Ставлю зависимости...
    call npm install --no-audit --no-fund
)

echo [*] Запускаю dev-сервер: http://127.0.0.1:5173
call npm run dev
pause
