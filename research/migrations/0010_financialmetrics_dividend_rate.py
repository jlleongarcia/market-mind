from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('research', '0009_dividend_payment_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialmetrics',
            name='dividend_rate',
            field=models.DecimalField(
                blank=True,
                decimal_places=4,
                help_text="Annual dividend per share in the stock's native currency (e.g. 3.32 for MSFT)",
                max_digits=8,
                null=True,
            ),
        ),
    ]
