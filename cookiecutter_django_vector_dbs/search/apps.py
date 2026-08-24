from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

class SearchConfig(AppConfig):
    name = "cookiecutter_django_vector_dbs.search"
    verbose_name = _("Search")
