import os
from django.core.asgi import get_asgi_application
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Gocabservices.settings.production")
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
import gocabapp.routing
from gocabapp.ws_auth import JWTAuthMiddlewareStack

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddlewareStack(
        URLRouter(gocabapp.routing.websocket_urlpatterns)
    ),
})