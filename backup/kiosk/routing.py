from django.urls import re_path
from . import consumers

# `STTConsumer` 대신 `AzureSTTConsumer` 사용
websocket_urlpatterns = [
    re_path(r'ws/audio/$', consumers.AzureSTTConsumer.as_asgi()),
]
