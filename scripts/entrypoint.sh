#!/bin/bash

# Exit on error
set -e

echo "Waiting for PostgreSQL..."
while ! nc -z $DATABASE_HOST $DATABASE_PORT; do
  sleep 0.1
done
echo "PostgreSQL started"

echo "Running migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput || true

echo "Creating superuser if it doesn't exist..."
python manage.py shell << END
from django.contrib.auth import get_user_model
from portfolio.models import UserProfile

User = get_user_model()
if not User.objects.filter(username='admin').exists():
    admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    # Create profile and force password change on first login
    profile, _ = UserProfile.objects.get_or_create(user=admin_user)
    profile.force_password_change = True
    profile.save()
    print('Superuser created: username=admin, password=admin123')
    print('⚠️  Admin must change password on first login')
else:
    print('Superuser already exists')
END

echo "Starting server on 0.0.0.0:8000..."
exec "$@"
