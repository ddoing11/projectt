from django.urls import path
from kiosk import views as kiosk_views
from . import views

urlpatterns = [
    # 메인 페이지들
    path('', kiosk_views.start, name='start'),
    path('start/', kiosk_views.start, name='start'),
    path('order/', kiosk_views.order, name='order'),
    path('order2/', kiosk_views.order2, name='order2'),
    path('pay_all', views.pay_all_view, name='pay_all'),
    path('pay_all2', views.pay_all2, name='pay_all2'),
    path('done/', views.done, name='done'),

    # API 엔드포인트들
    path('api/tts-token/', views.tts_token, name='tts_token'),  # 중요: TTS 토큰 발급
    path('check-menu/', kiosk_views.check_menu, name='check_menu'),
    path('gpt-assist/', kiosk_views.gpt_assist, name='gpt_assist'),
    path('add-to-cart/', kiosk_views.add_to_cart, name='add_to_cart'),

    # 팝업 페이지들
    path('popup/popup_coffee/', views.popup_coffee, name='popup_coffee'),
    path('popup/popup_drink/', views.popup_drink, name='popup_drink'),
    path('popup/popup_tea/', views.popup_tea, name='popup_tea'),

    # 더미 엔드포인트
    path('voice_socket/', views.voice_socket_dummy, name='voice_socket'),

    # 메뉴별 페이지들 (필요시)
    path('menu/coffee/', views.menu_coffee, name='menu_coffee'),
    path('menu/drink/', views.menu_drink, name='menu_drink'),
    path('menu/tea/', views.menu_tea, name='menu_tea'),
    path('menu/dessert/', views.menu_dessert, name='menu_dessert'),
]