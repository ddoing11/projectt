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
from django.http import FileResponse
from azure.cognitiveservices.speech import SpeechConfig, SpeechSynthesizer, AudioConfig
import uuid
import os

def voice_socket_dummy(request):
    return HttpResponse("voice_socket dummy - iframe용")

# [중요] 여기에 너의 openai 키를 설정해줘야 한다!
openai.api_key = '너의-openai-api-key'

# 시작 페이지
def start(request):
    return render(request, 'start.html')

def order(request):
    return render(request, 'order.html')

def order2(request):
    return render(request, 'order2.html')

from django.shortcuts import render
from kiosk.stt_ws_server import client_states

def pay_all(request):
    client_id = request.GET.get("client_id")
    print("🔍 받은 client_id:", client_id)

    cart = []
    for state in client_states.values():
        if str(state.get("client_id")) == str(client_id):
            cart = state.get("cart", [])
            break

    total_price = sum(item["price"] * item["count"] for item in cart)

    # ✅ cart_text 포맷: 정렬된 텍스트 형태로
    lines = []
    for item in cart:
        name = item["name"]
        count = item["count"]
        price = item["price"] * count
        lines.append(f"{name:<10} {count}개   {price:>6,}원")
    cart_text = "\n".join(lines)

    return render(request, 'pay_all.html', {
        "cart": cart,
        "total_price": total_price,
        "cart_text": cart_text  # ✅ HTML에서 {{ cart_text }}로 출력됨
    })



def pay_all2(request):
    return render(request, 'pay_all2.html')


def menu_coffee(request):
    return render(request, 'menu_coffee.html')

def menu_drink(request):
    return render(request, 'menu_drink.html')

def menu_drink2(request):
    return render(request, 'menu_drink2.html')

def menu_tea(request):
    return render(request, 'menu_tea.html')

def menu_dessert(request):
    return render(request, 'menu_dessert.html')

def voice_socket_view(request):
    return render(request, 'voice_socket.html')

from kiosk import stt_ws_server



def pay_all_view(request):
    client_id = request.GET.get("client_id")
    state = stt_ws_server.client_sessions.get(client_id)

    cart_items = []
    total_price = 0
    lines = []

    if state:
        for item in state.get("cart", []):
            name = item["name"]
            count = item.get("count", 1)
            price = int(item["price"])
            total = price * count

            # 장바구니용 데이터 저장
            cart_items.append({
                "name": name,
                "count": count,
                "price": price,
            })

            total_price += total

            # 줄 정렬된 텍스트 줄 추가 (예: 아메리카노     1개    2,000원)
            lines.append(f"{name:<10} {str(count)+'개':<6} {total:>6,}원")

    # 최종 텍스트로 변환
    cart_text = "\n".join(lines)
    cart_text += f"\n\n총 결제 금액은 {int(total_price):,}원입니다."

    return render(request, 'pay_all.html', {
        "cart": cart_items,
        "total_price": total_price,
        "cart_text": cart_text
    })


def make_cart_summary(cart, total):
    lines = []
    for item in cart:
        lines.append(f"- {item['name']}  {item['count']}개에 {int(item['price'])}원")
    lines.append(f"총 결제 금액은 {int(total)}원입니다.")
    return "\n".join(lines)


def popup_coffee(request):
    return render(request, 'popup/popup_coffee.html')

def popup_drink(request):
    return render(request, 'popup/popup_drink.html')

def popup_tea(request):
    print("🧪 popup_tea view 호출됨")
    return render(request, 'popup/popup_tea.html')



def done(request):
    return render(request, 'done.html') 


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
