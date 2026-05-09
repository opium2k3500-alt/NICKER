#!/bin/bash
set -e
python3 bot.py &
exec gunicorn server:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120
