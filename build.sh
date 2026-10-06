#!/usr/bin/env bash
# Render build step. The SQLite database is rebuilt from data/ on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py load_data
