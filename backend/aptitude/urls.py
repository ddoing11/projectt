from django.contrib import admin

from kiosk import views as kiosk_views
from aptitude import views
from django.urls import path, include
from aptitude import views as aptitude_views 

urlpatterns = [
    path('admin/', admin.site.urls),
    path('start/', kiosk_views.start, name='start'),
    path('order/', kiosk_views.order, name='order'),
    path('check-menu/', kiosk_views.check_menu, name='check_menu'),
    path('gpt-assist/', kiosk_views.gpt_assist, name='gpt_assist'),
    path('add-to-cart/', kiosk_views.add_to_cart, name='add_to_cart'),
    path('menu_coffee/', views.menu_coffee, name='menu_coffee'),
    path('menu_drink/', views.menu_drink, name='menu_drink'),
    path('menu_tea/', views.menu_tea, name='menu_tea'),
    path('menu_dessert/', views.menu_dessert, name='menu_dessert'),
    path('menu_drink_2/', views.menu_drink_2, name='menu_drink_2'),
    path('popup-coffee/', views.popup_coffee, name='popup_coffee'),   
    path('popup-drink/', aptitude_views.popup_drink, name='popup_drink'),
    path('popup/tea/', views.popup_tea, name='popup_tea'),
    path('pay_all/', views.pay_all, name='pay_all'),
    path('done/', views.done, name='done'),
    path('payment_final/', views.payment_final, name='payment_final'),
    
    path('', include('kiosk.urls')),
]

