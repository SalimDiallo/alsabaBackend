# Compatibilité django-fernet-fields avec Django 4+ (force_text → force_str)
import django.utils.encoding
if not hasattr(django.utils.encoding, 'force_text'):
    django.utils.encoding.force_text = django.utils.encoding.force_str

# Celery import désactivé temporairement (module non installé dans l'image)
# from .celery import app as celery_app
# __all__ = ('celery_app',)
