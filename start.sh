#!/bin/bash
set -e

# Создаём директорию для БД если не существует
mkdir -p /data 2>/dev/null || true

# Запускаем веб-сервер
gunicorn server:app \
  --bind 0.0.0.0:${PORT:-5000} \
  --workers 1 \
  --timeout 120 \
  --log-level info \
  &
GUNICORN_PID=$!

# Ждём пока gunicorn готов (через Python — curl может отсутствовать)
python3 - <<'PYEOF'
import time, urllib.request, os
port = os.getenv("PORT", "5000")
url  = f"http://localhost:{port}/api/stats"
for _ in range(30):
    try:
        urllib.request.urlopen(url, timeout=2)
        print(f"Gunicorn ready on :{port}")
        break
    except Exception:
        time.sleep(1)
PYEOF

# Запускаем бота (держит контейнер живым)
python3 bot.py &
BOT_PID=$!

# Ждём любого из процессов
wait -n $GUNICORN_PID $BOT_PID 2>/dev/null || wait $GUNICORN_PID $BOT_PID
