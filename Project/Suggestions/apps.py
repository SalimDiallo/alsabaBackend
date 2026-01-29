from django.apps import AppConfig


class SuggestionsConfig(AppConfig):
    name = 'Suggestions'

    def ready(self):
        import Suggestions.signals
