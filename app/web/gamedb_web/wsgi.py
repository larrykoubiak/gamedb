"""WSGI config for GameDB."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.web.gamedb_web.settings")

application = get_wsgi_application()
