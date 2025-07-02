from asgiref.sync import sync_to_async
from django.db import connection
from django.db.utils import OperationalError
from kiosk.models import MenuItem


@sync_to_async
def ensure_mysql_connection():
    """MySQL 연결 확인 및 재연결"""
    try:
        connection.cursor()
    except OperationalError:
        connection.close()


@sync_to_async
def get_price_from_db(menu_name):
    """데이터베이스에서 메뉴 가격 조회"""
    try:
        item = MenuItem.objects.get(name=menu_name)
        return float(item.price)
    except MenuItem.DoesNotExist:
        print(f"❌ 메뉴 '{menu_name}'에 대한 가격 정보를 찾을 수 없습니다.")
        return 0  # 기본값 처리