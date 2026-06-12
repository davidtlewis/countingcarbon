web: gunicorn countingcarbon.wsgi --workers 2 --threads 2 --log-file -
release: uv run python manage.py migrate --no-input && uv run python manage.py collectstatic --no-input
