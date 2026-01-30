# Generated migration for KYCDocument audit fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Accounts', '0002_user_kyc_expires_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='kycdocument',
            name='accessed_at',
            field=models.DateTimeField(blank=True, help_text='Dernière consultation', null=True),
        ),
        migrations.AddField(
            model_name='kycdocument',
            name='accessed_by',
            field=models.CharField(blank=True, help_text='ID de qui a consulté', max_length=100),
        ),
        migrations.AddIndex(
            model_name='kycdocument',
            index=models.Index(fields=['user', 'verification_status'], name='kyc_documents_user_status_idx'),
        ),
        migrations.AddIndex(
            model_name='kycdocument',
            index=models.Index(fields=['created_at'], name='kyc_documents_created_at_idx'),
        ),
    ]
