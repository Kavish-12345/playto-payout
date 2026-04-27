#!/bin/bash
set -e

echo "Running migrations..."
python manage.py migrate

echo "Seeding database..."
python manage.py seed

echo "Starting Django-Q worker..."
python manage.py qcluster &

echo "Starting Gunicorn..."
gunicorn core.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120