#!/bin/bash
# Запускаем веб-сервер в фоне
gunicorn server:app --bind 0.0.0.0:${PORT:-5000} --workers 1 --timeout 120 --daemon \
  --log-file /tmp/gunicorn.log --pid /tmp/gunicorn.pid

# Ждём пока gunicorn готов (до 30 секунд)
for i in $(seq 1 30); do
  if curl -sf http://localhost:${PORT:-5000}/api/stats > /dev/null 2>&1; then
    echo "Gunicorn ready after ${i}s"
    break
  fi
  sleep 1
done

# Запускаем бота (он работает бесконечно — держим процесс живым)
exec python3 bot.py
