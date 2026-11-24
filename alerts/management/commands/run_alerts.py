"""
Evaluate every user's alert rules and built-in warnings, then send each user
one digest (email and/or Telegram). Runs daily via cron after the financial
metrics refresh — see scripts/run_alerts.sh.
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from alerts.services import AlertEngine


class Command(BaseCommand):
    help = 'Evaluate alert rules and send notification digests'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Print what would fire without saving state, events or sending anything')
        parser.add_argument('--user', type=str, help='Only run for this username')

    def handle(self, *args, **options):
        users = User.objects.filter(is_active=True)
        if options['user']:
            users = users.filter(username=options['user'])

        summary = AlertEngine(dry_run=options['dry_run']).run(users=users, stdout=self.stdout)
        for username, status, count in summary:
            self.stdout.write(f"{username}: {count} new alert(s) — {status}")
