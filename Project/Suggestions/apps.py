from django.apps import AppConfig


class SuggestionsConfig(AppConfig):
    name = 'Suggestions'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        pass
