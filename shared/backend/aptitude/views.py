from django.shortcuts import render
from django.http import JsonResponse
from kiosk.models import MenuItem
import json
from django.views.decorators.csrf import csrf_exempt
import openai

# ChatGPT 설정 (API 키는 settings에 보관하는 것이 좋음)
openai.api_key = "YOUR_OPENAI_API_KEY"

# --- 시작 화면 ---
def start(request):
    return render(request, 'start.html')

# --- 음성 주문 시작 화면 ---
def order_start_voice(request):
    return render(request, 'kiosk/order_start_voice.html')

# --- 주문 화면 ---
def order(request):
    return render(request, 'order.html')

# --- 음성 인식 결과 처리 ---
@csrf_exempt
def process_response(request):
    if request.method == "POST":
        body = json.loads(request.body)
        user_response = body.get("response", "").lower()

        positive_keywords = ["네", "응", "좋아", "그래", "예", "오케이", "ㅇㅇ", "어", "주문 시작", "주문할래", "주문해"]

        if any(p in user_response for p in positive_keywords):
            return JsonResponse({"response": "음성 주문을 시작합니다. 어떤 메뉴를 원하시나요?"})
        else:
            return JsonResponse({"response": "일반 키오스크 주문으로 진행해 주세요."})

    return JsonResponse({"error": "Invalid request"}, status=400)

# --- 사용자의 음성 텍스트로 메뉴 매칭 ---
@csrf_exempt
def speech_to_text(request):
    if request.method == "POST":
        body = json.loads(request.body)
        user_text = body.get("text", "").strip()

        menu_items = MenuItem.objects.all()
        menu_names = [item.name for item in menu_items]

        matched_menu = next((name for name in menu_names if name in user_text), None)

        if matched_menu:
            return JsonResponse({"matched": True, "menu_name": matched_menu})
        else:
            return JsonResponse({"matched": False, "text": user_text})

    return JsonResponse({"error": "Invalid request"}, status=400)

# --- 메뉴에 대한 상세 옵션 선택 질문 ---
@csrf_exempt
def select_options(request):
    if request.method == "POST":
        body = json.loads(request.body)
        menu_name = body.get("menu_name")

        try:
            menu = MenuItem.objects.get(name=menu_name)
            category = menu.category

            if category in ["coffee", "drink"]:
                question = "사이즈는 보통과 크게 중 어떤 걸로 하시겠어요? 그리고 핫/아이스를 선택해주세요. 추가 샷은 안함, 1번(300원 추가), 2번(600원 추가) 중에 골라주세요."
            elif category == "tea":
                question = "사이즈는 보통과 크게 중 어떤 걸로 하시겠어요? 그리고 핫/아이스를 선택해주세요."
            else:
                question = None

            if question:
                return JsonResponse({"need_options": True, "question": question})
            else:
                return JsonResponse({"need_options": False, "message": "옵션 선택이 필요 없는 메뉴입니다."})

        except MenuItem.DoesNotExist:
            return JsonResponse({"error": "메뉴를 찾을 수 없습니다."}, status=404)

    return JsonResponse({"error": "Invalid request"}, status=400)

# --- ChatGPT로 대화 흐름 이어가기 ---
@csrf_exempt
def chatgpt_order(request):
    if request.method == "POST":
        body = json.loads(request.body)
        user_text = body.get("text", "")

        prompt = f"고객이 '{user_text}'라고 했습니다. 이 요청에 맞는 메뉴를 추천하고 부드럽게 대화형으로 주문을 유도하세요. 단, 메뉴는 '아메리카노, 카페라떼, 달고나 라떼, 토피넛라떼, 초코라떼, 녹차 라떼, 딸기 라떼, 요거트 스무디, 아이스티, 아샷추, 레몬에이드, 자몽에이드, 캐모마일, 루이보스, 히비스커스, 얼그레이, 베이글, 카스테라, 딸기케이크, 초코케이크' 중에서만 추천해야 합니다."

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "너는 음료 추천 키오스크야."},
                    {"role": "user", "content": prompt}
                ]
            )

            gpt_reply = response.choices[0].message['content'].strip()

            return JsonResponse({"response": gpt_reply})

        except Exception as e:
            print("ChatGPT 오류:", e)
            return JsonResponse({"error": "ChatGPT 오류"}, status=500)

    return JsonResponse({"error": "Invalid request"}, status=400)

# --- 웹소켓 테스트용 ---
def websocket_test(request):
    return render(request, 'kiosk/websocket_test.html')