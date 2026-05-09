#!/bin/bash
# Запускаем бота в фоне (не блокирует запуск сервера)
python3 bot.py &

# Даём боту секунду чтобы инициализировать БД
sleep 2

# Запускаем веб-сервер
exec gunicorn server:app --bind 0.0.0.0:${PORT:-5000} --workers 1 --timeout 120
