# Generated migration for Dispute model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('Offer', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Dispute',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('reason', models.CharField(max_length=500)),
                ('evidence', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(
                    choices=[
                        ('open', 'Ouvert'),
                        ('under_review', 'Sous revue'),
                        ('resolved', 'Résolu'),
                        ('escalated', 'Escaladé (Support manuel)'),
                    ],
                    db_index=True,
                    default='open',
                    max_length=20
                )),
                ('resolution', models.CharField(
                    blank=True,
                    choices=[
                        ('refund_a1', 'Remboursement A1'),
                        ('refund_a2', 'Remboursement A2'),
                        ('split', 'Partage 50/50'),
                        ('pending', 'En attente'),
                    ],
                    default='pending',
                    max_length=20
                )),
                ('admin_notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('initiated_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='disputes_initiated', to=settings.AUTH_USER_MODEL)),
                ('offer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='disputes', to='Offer.offer')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='disputes_reviewed', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'offer_disputes',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='dispute',
            index=models.Index(fields=['offer', 'status'], name='offer_dispu_offer_id_status_idx'),
        ),
        migrations.AddIndex(
            model_name='dispute',
            index=models.Index(fields=['initiated_by', 'created_at'], name='offer_dispu_initiat_created_idx'),
        ),
    ]
