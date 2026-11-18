# Алиса AI — Discord Activity с 2.5D-аватаром

> 📖 **Пошаговый запуск: [ЗАПУСК.md](ЗАПУСК.md)** — там всё от установки FFmpeg до туннелей.

Голосовой AI-ассистент в Discord с визуализацией внутри Activity:
липсинк по 48 формам рта, 9 эмоций, субтитры, история, зоны поглаживания/тыканья.
Wake-word: **«helper»** (и «хелпер»).

```
alisa-activity/
├── backend/    # discord-бот (Python) + FastAPI WebSocket-мост
└── frontend/   # Discord Activity (React + Vite + canvas-рендер аватара)
```

## Архитектура

- **Аудио** остаётся в голосовом канале Discord (бот говорит через edge-tts).
- **Анимация**: бот шлёт в Activity по WebSocket (`/ws`):
  - `status` — Слушаю/Думаю/Отвечаю/На паузе
  - `answer_start` — текст ответа + эмоция (из 9)
  - `words` — тайминги слов от edge-tts (для липсинка)
  - `history`, `stop`, `voice`
- **Правило речи**: пока Алиса отвечает — весь ввод игнорируется.
  Прервать: сказать/написать «стоп» / «stop», или кнопка ■ в Activity.

## Запуск (разработка)

### 1. Бэкенд
```
cd backend
start.bat          # uv сам создаст venv и поставит зависимости
```
Токены берутся из `backend/env/.env` (DISCORD_BOT_TOKEN, GEMINI_API_KEY и т.д. — см. env/.env.example).

### 2. Фронтенд (просто в браузере)
```
cd frontend
start.bat          # npm install + vite на http://127.0.0.1:5173
```
В браузере моделька работает с локальным мостом `ws://127.0.0.1:8765/ws`.

### 3. Внутри Discord (через cloudflared)

1. Скачай cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Два туннеля (в двух консолях):
   ```
   cloudflared tunnel --url http://127.0.0.1:5173
   cloudflared tunnel --url http://127.0.0.1:8765
   ```
   Первый даст `https://xxx.trycloudflare.com` (страница), второй — URL моста.
3. Пропиши мост при сборке (создай `frontend/.env.local`):
   ```
   VITE_BRIDGE_URL=wss://yyy.trycloudflare.com/ws
   ```
   (https-страница Discord не может открывать plain ws:// — mixed content,
   поэтому мост тоже идёт через туннель)
4. Discord Developer Portal → твоё приложение:
   - **Activities** → включить, URL Mapping: `/` → `https://xxx.trycloudflare.com`
   - В боте должны быть включены Intent'ы (message content, voice states, members)
5. Запусти Activity из голосового канала (значок ракеты/Activity) или `/join` + открыть Activity.
6. URL туннелей меняются при перезапуске — обнови Mapping и `.env.local`.

### Команды бота
- `/join` — зайти в голосовой канал
- `/leave` — выйти
- Всё остальное — в UI Activity (голос, субтитры, громкость, фон, история, стоп).

## Тесты

- Липсинк-синхронизация (реальный edge-tts + таймлайн): 
  `cd frontend && uv run --with edge-tts python test/sync_test.py`
- Фейковый мост для ручной проверки анимации: `backend/test_fake_bridge.py`

## Ассеты

Используются только готовые спрайты из проекта риггинг-студии:
`alisa_expressions_cutout.png` (9 эмоций, 3×3), `alisa_expressions_mouthless_cutout.png`,
`alisa_visemes_48_cutout.png` (48 форм рта). Новая графика не создавалась.
