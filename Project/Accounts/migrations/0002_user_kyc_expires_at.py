from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='kyc_expires_at',
            field=models.DateField(blank=True, help_text='✅ KYC expiration date for compliance', null=True),
        ),
    ]
