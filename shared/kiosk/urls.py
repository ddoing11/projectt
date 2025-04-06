from django.urls import path
from . import views

urlpatterns = [
    path('', views.start, name='start'),    # 기본 페이지 설정
    path('order/', views.order, name = 'order'),    # 주문 페이지 
    path('speech-to-text/', views.speech_to_text, name='speech_to_text'),  # 음성인식 API
]

