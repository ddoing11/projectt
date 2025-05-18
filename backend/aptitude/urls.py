from django.contrib import admin

from kiosk import views as kiosk_views
from kiosk import views
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('start/', kiosk_views.start, name='start'),
    path('order/', kiosk_views.order, name='order'),
    path('check-menu/', kiosk_views.check_menu, name='check_menu'),
    path('gpt-assist/', kiosk_views.gpt_assist, name='gpt_assist'),
    path('add-to-cart/', kiosk_views.add_to_cart, name='add_to_cart'),
    path('', include('kiosk.urls')),
    path("popup/popup_drink/", views.popup_drink, name='popup_drink'),
    path("popup/popup_tea/", views.popup_tea, name='popup_tea'),
    path('popup/popup_coffee/', views.popup_coffee, name='popup_coffee'),
    path('pay_all', views.pay_all, name='pay_all'),
    path('done/', views.done, name='done'),
]

