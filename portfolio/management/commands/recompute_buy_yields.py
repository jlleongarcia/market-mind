"""
One-off management command to recompute buy_yield on all existing BUY
transactions, e.g. after backfilling declaration_date on Dividend records.
"""
from django.core.management.base import BaseCommand

from portfolio.models import Transaction
from portfolio.services import PortfolioCalculationService


class Command(BaseCommand):
    help = 'Recompute buy_yield for all BUY transactions'

    def handle(self, *args, **options):
        transactions = Transaction.objects.filter(transaction_type='BUY').order_by('transaction_date')
        total = transactions.count()
        self.stdout.write(f"Recomputing buy_yield for {total} BUY transaction(s)\n")

        updated = 0
        skipped = 0

        for tx in transactions:
            if PortfolioCalculationService.fetch_and_store_buy_yield(tx):
                updated += 1
            else:
                skipped += 1

        self.stdout.write(
            f"\n{'='*50}\n"
            f"Summary: {updated} updated, {skipped} skipped (no dividend data)\n"
            f"{'='*50}\n"
        )
