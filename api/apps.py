from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        from .firebase_config import initialize_firebase
        initialize_firebase()
