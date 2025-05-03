from django.contrib import admin
from django.urls import path
from kiosk import views as kiosk_views
from . import views
from django.views.generic import TemplateView

urlpatterns = [

    path('', kiosk_views.start, name='start'),
    path('order/', kiosk_views.order, name='order'),
    
    # 새로 추가된 올바른 라우팅
    path('check-menu/', kiosk_views.check_menu, name='check_menu'),
    path('gpt-assist/', kiosk_views.gpt_assist, name='gpt_assist'),
    path('add-to-cart/', kiosk_views.add_to_cart, name='add_to_cart'),

    path('voice_socket/', views.voice_socket_dummy, name='voice_socket'),

]
