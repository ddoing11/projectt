from django.shortcuts import render
from django.http import JsonResponse
from .speech_processing import transcribe_audio
from .chatbot import get_chatbot_response
from .models import SpeechCommand, Menu, Cart
import whisper
import random
import openai

# OpenAI API 키 설정
OPENAI_API_KEY = "your-openai-api-key"

# 미리 정해둔 키워드별 추천 가능한 메뉴 리스트
menu_recommendations = {
    "단": ["초코라떼", "바닐라 라떼", "청포도 에이드", "생딸기 라떼"],
    "거": ["초코라떼", "토피넛 라떼", "레몬에이드"],
    "시원한": ["아이스 아메리카노", "레몬에이드", "청포도 에이드"],
    "따뜻한": ["카페라떼", "핫 초코", "얼그레이"]
}

# 실제 주문 가능한 메뉴 목록 및 가격
menu_items = {
    "아메리카노": "아메리카노 2,500원 입니다.",
    "카페라떼": "카페라떼 3,000원 입니다.",
    "바닐라 라떼": "바닐라 라떼 3,500원 입니다.",
    "초코라떼": "초코라떼 4,000원 입니다.",
    "레몬에이드": "레몬에이드 3,800원 입니다.",
    "청포도 에이드": "청포도 에이드 3,500원 입니다.",
    "생딸기 라떼": "생딸기 라떼 4,500원 입니다."
}

def start(request):
    return render(request, 'start.html')

def order(request):
    return render(request, 'order.html')

def speech_to_text(request):
    if request.method == "POST":
        audio_file = request.FILES.get("audio")
        if not audio_file:
            return JsonResponse({"error": "No audio file provided"}, status=400)

        model = whisper.load_model("base")
        result = model.transcribe(audio_file.read())
        user_text = result["text"]
        words = user_text.split()

        command = SpeechCommand.objects.filter(input_text=user_text).first()
        if command:
            command.recommended += 1
            command.save()
            return JsonResponse({"response": command.response_text})

        temperature = None
        if "차가운" in words or "시원한" in words:
            temperature = "ice"
        elif "따뜻한" in words or "뜨거운" in words:
            temperature = "hot"

        matched_menu = next((word for word in words if word in menu_items), None)

        recommended_menus = [item for word in words for item in menu_recommendations.get(word, [])]

        if matched_menu:
            if temperature:
                response_text = f"{menu_items[matched_menu]} ({'ICE' if temperature == 'ice' else 'HOT'})로 구매하시겠습니까?"
            else:
                request.session["recommendation"] = matched_menu
                return JsonResponse({"response": "차가운 것으로 하시겠습니까, 따뜻한 것으로 하시겠습니까?"})

        elif recommended_menus:
            if "달지 않고 시원한" in user_text:
                temperature = "ice"
                random_menu = random.choice(recommended_menus)
                response_text = f"{random_menu}({temperature})는 어떠세요? 구매하시겠습니까?"
            elif "달지 않은" in user_text:
                request.session["recommendation"] = random.choice(recommended_menus)
                return JsonResponse({"response": "차가운 것으로 하시겠습니까, 따뜻한 것으로 하시겠습니까?"})
            else:
                random_menu = random.choice(recommended_menus)
                response_text = f"{random_menu}는 어떠세요? 구매하시겠습니까?"
                request.session["recommendation"] = random_menu
        else:
            response_text = get_chatgpt_recommendation(user_text)

        return JsonResponse({"response": response_text})

    return JsonResponse({"error": "Invalid request"}, status=400)

def get_chatgpt_recommendation(user_request):
    openai.api_key = OPENAI_API_KEY
    prompt = f"카페에서 제공하는 메뉴는 {list(menu_items.keys())} 입니다. 사용자가 '{user_request}' 라고 말했을 때, 가장 적절한 메뉴를 추천해주세요."

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": prompt}]
    )

    return response["choices"][0]["message"]["content"]

def add_to_cart(request):
    if request.method == "POST":
        user_text = request.POST.get("text", "")
        words = user_text.split()

        if any(word in ["네", "응", "좋아"] for word in words):
            recommendation = request.session.get("recommendation")
            temperature = request.session.get("temperature", "ice")

            if recommendation:
                cart_item = Cart(menu_item=Menu.objects.get(name=recommendation), option=temperature)
                cart_item.save()
                request.session["recommendation"] = None
                return JsonResponse({"response": f"{recommendation}({temperature})을 장바구니에 추가했습니다. 또 주문하시겠습니까?"})

        if any(word in ["아니", "아니요", "괜찮아"] for word in words):
            return JsonResponse({"response": "결제 페이지로 이동합니다."})

    return JsonResponse({"error": "Invalid request"}, status=400)

def checkout(request):
    cart_items = Cart.objects.filter(ordered=False)
    total_price = sum(getattr(item.menu_item, "price", 0) for item in cart_items)

    if request.method == "POST":
        for item in cart_items:
            item.ordered = True
            item.save()

        return JsonResponse({"response": f"총 {total_price}원입니다. 결제가 완료되었습니다."})

    return render(request, "checkout.html", {"cart_items": cart_items, "total_price": total_price})
