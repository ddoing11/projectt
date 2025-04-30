# backend/aptitude/asgi.py

import os
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from django.core.asgi import get_asgi_application
from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
import kiosk.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aptitude.settings')

# 기존 get_asgi_application 감싸기
django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": ASGIStaticFilesHandler(django_asgi_app),  #  static files 서빙
    "websocket": AuthMiddlewareStack(
        URLRouter(
            kiosk.routing.websocket_urlpatterns
        )
    ),
})
