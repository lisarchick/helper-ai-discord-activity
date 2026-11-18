@echo off
chcp 65001 >nul
REM === Alisa AI backend (Discord bot + Activity WebSocket bridge) ===
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [!] uv не найден. Установи: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [*] Создаю venv...
    uv venv
)

echo [*] Ставлю зависимости...
uv pip install -r requirements.txt

echo [*] Запускаю Алису (бот + WS-мост на 127.0.0.1:8765)...
uv run bot.py
pause
