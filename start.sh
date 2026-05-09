#!/bin/bash
set -e
exec gunicorn server:app --bind 0.0.0.0:${PORT:-5000} --workers 2 --timeout 120
