from django.apps import AppConfig


class LeavesConfig(AppConfig):
    default_app_config = 'leaves.apps.LeavesConfig'
    name = 'leaves'
    
    
    
    def ready(self):
        #import leaves.signals  # Pour les signaux si vous en avez
        import leaves.templatetags.leaves_filters  # Pour les filtres
