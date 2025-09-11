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
        return 0

@sync_to_async
def get_menu_by_name(menu_name):
    """메뉴 이름으로 메뉴 아이템 조회"""
    try:
        return MenuItem.objects.get(name=menu_name)
    except MenuItem.DoesNotExist:
        return None

@sync_to_async
def get_menus_by_category(category):
    """카테고리별 메뉴 조회"""
    return list(MenuItem.objects.filter(category=category))

@sync_to_async
def get_all_menus():
    """모든 메뉴 조회"""
    return list(MenuItem.objects.all())

def calculate_item_price(base_price, options):
    """옵션을 고려한 최종 가격 계산"""
    extra_price = 0
    
    # 사이즈 추가 요금
    if options.get("size") == "큰":
        extra_price += 500
    
    # 샷 추가 요금
    shot = options.get("shot")
    if shot == "1샷":
        extra_price += 300
    elif shot == "2샷":
        extra_price += 600
    
    return base_price + extra_price

def create_cart_item(name, category, base_price, options=None, count=1):
    """장바구니 아이템 생성"""
    if options is None:
        options = {}
    
    final_price = calculate_item_price(base_price, options)
    
    return {
        "name": name,
        "category": category,
        "options": options.copy(),
        "price": final_price,
        "count": count,
        "total_price": final_price * count
    }

def get_default_options(category):
    """카테고리별 기본 옵션 반환"""
    if category in ["커피", "음료"]:
        return {"size": "보통", "temp": "아이스", "shot": "없음"}
    elif category == "차":
        return {"size": "보통", "temp": "아이스"}
    else:  # 디저트
        return {}