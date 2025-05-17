# kiosk/views.py
from django.shortcuts import render
from django.http import JsonResponse
from .models import MenuItem
import json
import openai  # ChatGPT 호출용
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.http import HttpResponse
from django.shortcuts import render

def voice_socket_dummy(request):
    return HttpResponse("voice_socket dummy - iframe용")

# [중요] 여기에 너의 openai 키를 설정해줘야 한다!
openai.api_key = '너의-openai-api-key'

# 시작 페이지
def start(request):
    return render(request, 'start.html')

def order(request):
    return render(request, 'order.html')

def voice_socket_view(request):
    return render(request, 'voice_socket.html')

def popup_coffee(request):
    return render(request, 'popup/popup_coffee.html')

def popup_drink(request):
    return render(request, 'popup/popup_drink.html')

def popup_tea(request):
    print("🧪 popup_tea view 호출됨")
    return render(request, 'popup/popup_tea.html')


def pay_all(request):
    return render(request, 'pay_all.html')

@csrf_exempt
def check_menu(request):
    if request.method == "POST":
        data = json.loads(request.body)
        user_text = data.get("text", "").strip()

        menu_items = MenuItem.objects.all()
        menu_names = [item.name for item in menu_items]

        # 메뉴 이름이 텍스트에 포함되어 있으면 매칭
        matched_menu = next((name for name in menu_names if name in user_text), None)

        if matched_menu:
            menu = MenuItem.objects.get(name=matched_menu)
            return JsonResponse({
                "found": True,
                "menu": matched_menu,
                "price": menu.price,
                "category": menu.category
            })
        else:
            return JsonResponse({"found": False})
    return JsonResponse({"error": "Invalid request"}, status=400)

@csrf_exempt
def gpt_assist(request):
    if request.method == "POST":
        data = json.loads(request.body)
        user_text = data.get("text", "").strip()

        # DB에서 메뉴 이름 모음
        menu_items = MenuItem.objects.all()
        menu_list = "\n".join(f"{item.name} ({item.price}원)" for item in menu_items)

        prompt = f"""너는 카페 직원이야.
사용자가 "{user_text}"라고 말했다고 가정해.
아래 메뉴 리스트 중에서 가장 어울리는 메뉴를 친절하게 추천하고, 필요하면 따듯한지, 아이스인지 물어봐.

메뉴 목록:
{menu_list}

대답할 때는 자연스럽게 짧고 부드럽게 말해줘. (예: "달콤한 음료를 찾고 계시군요! 딸기라떼 추천드릴게요.")"""

        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )

        gpt_reply = response['choices'][0]['message']['content'].strip()
        return JsonResponse({"response": gpt_reply})
    return JsonResponse({"error": "Invalid request"}, status=400)

@csrf_exempt
def add_to_cart(request):
    if request.method == "POST":
        data = json.loads(request.body)
        menu_name = data.get("menu")
        options = data.get("options", {})

        # 장바구니를 세션에 저장
        cart = request.session.get("cart", [])

        # 가격 계산
        try:
            menu = MenuItem.objects.get(name=menu_name)
            final_price = menu.price

            # 옵션 반영
            if options.get("size") == "크게":
                final_price += 500
            if options.get("shot") == "1샷추가":
                final_price += 300
            elif options.get("shot") == "2샷추가":
                final_price += 600

            cart.append({
                "menu": menu_name,
                "options": options,
                "price": final_price
            })

            request.session["cart"] = cart

            return JsonResponse({"success": True, "cart": cart})
        except MenuItem.DoesNotExist:
            return JsonResponse({"success": False, "error": "메뉴를 찾을 수 없습니다."})
    return JsonResponse({"error": "Invalid request"}, status=400)
