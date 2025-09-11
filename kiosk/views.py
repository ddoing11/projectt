# kiosk/views.py - 수정된 버전
from django.shortcuts import render
from django.http import JsonResponse
from .models import MenuItem
import json
import requests
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

@csrf_exempt
def tts_token(request):
    """Azure TTS 토큰 발급"""
    speech_key = getattr(settings, 'AZURE_SPEECH_KEY', None)
    region = getattr(settings, 'AZURE_SPEECH_REGION', None)
    
    if not speech_key or not region:
        return JsonResponse({"error": "Missing speech key or region."}, status=500)

    token_url = f"https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
    response = requests.post(
        token_url,
        headers={"Ocp-Apim-Subscription-Key": speech_key},
    )
    
    if response.status_code == 200:
        return JsonResponse({"token": response.text, "region": region})
    return JsonResponse({"error": "Failed to obtain token."}, status=500)

def start(request):
    return render(request, 'start.html')

def order(request):
    return render(request, 'order.html')

def order2(request):
    return render(request, 'order2.html')

def pay_all_view(request):
    """결제 페이지 - 단순화된 버전"""
    client_id = request.GET.get("client_id")
    
    # 기본 빈 카트로 시작 (실제 데이터는 WebSocket으로 업데이트)
    context = {
        "cart": [],
        "total_price": 0,
        "cart_text": "주문 내역을 불러오는 중...",
        "client_id": client_id
    }
    
    return render(request, 'pay_all.html', context)

def pay_all2(request):
    return render(request, 'pay_all2.html')

def done(request):
    return render(request, 'done.html')

def popup_coffee(request):
    return render(request, 'popup/popup_coffee.html')

def popup_drink(request):
    return render(request, 'popup/popup_drink.html')

def popup_tea(request):
    return render(request, 'popup/popup_tea.html')

def voice_socket_dummy(request):
    return JsonResponse({"status": "ok", "message": "voice socket endpoint"})

# 기존 GPT 관련 뷰들은 새로운 서버에서 처리하므로 제거 또는 단순화
@csrf_exempt
def check_menu(request):
    """메뉴 확인 - 단순화된 버전"""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_text = data.get("text", "").strip().lower()
            
            menu_items = MenuItem.objects.all()
            
            for item in menu_items:
                if item.name.lower() in user_text:
                    return JsonResponse({
                        "found": True,
                        "menu": item.name,
                        "price": float(item.price),
                        "category": item.category
                    })
            
            return JsonResponse({"found": False})
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)
    
    return JsonResponse({"error": "Invalid request"}, status=400)

@csrf_exempt 
def gpt_assist(request):
    """GPT 지원 - 웹소켓 서버로 이관됨"""
    return JsonResponse({
        "response": "GPT 기능은 음성 주문에서 사용 가능합니다."
    })

@csrf_exempt
def add_to_cart(request):
    """장바구니 추가 - 웹소켓 서버로 이관됨"""
    return JsonResponse({
        "success": True,
        "message": "음성 주문을 사용해주세요."
    })

# 메뉴별 뷰들
def menu_coffee(request):
    return render(request, 'menu_coffee.html')

def menu_drink(request):
    return render(request, 'menu_drink.html')

def menu_tea(request):
    return render(request, 'menu_tea.html')

def menu_dessert(request):
    return render(request, 'menu_dessert.html')