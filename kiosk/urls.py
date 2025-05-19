from django.contrib import admin
from django.urls import path
from kiosk import views as kiosk_views
from . import views
from django.views.generic import TemplateView

urlpatterns = [

    path('', kiosk_views.start, name='start'),
    path('order/', kiosk_views.order, name='order'),
    path('order2/', kiosk_views.order2, name='order2'),
    # 새로 추가된 올바른 라우팅
    path('check-menu/', kiosk_views.check_menu, name='check_menu'),
    path('gpt-assist/', kiosk_views.gpt_assist, name='gpt_assist'),
    path('add-to-cart/', kiosk_views.add_to_cart, name='add_to_cart'),
    path('popup/popup_coffee/', views.popup_coffee, name='popup_coffee'),
    path('voice_socket/', views.voice_socket_dummy, name='voice_socket'),
    path("popup/popup_drink/", views.popup_drink, name='popup_drink'),
    path("popup/popup_tea/", views.popup_tea, name='popup_tea'),
    path('pay_all', views.pay_all, name='pay_all'),
    path('done/', views.done, name='done'),
    path('menu/coffee/', views.menu_coffee, name='menu_coffee'),
    path('menu/drink/', views.menu_drink, name='menu_drink'),
    path('menu/tea/', views.menu_tea, name='menu_tea'),
    path('menu/dessert/', views.menu_dessert, name='menu_dessert'),


]
