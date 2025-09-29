import asyncio
import websockets
import os
import sys
import re
import difflib
import time
from asgiref.sync import sync_to_async
from difflib import SequenceMatcher
from playsound import playsound
import threading
from django.db import connection
from django.db.utils import OperationalError
from websockets.exceptions import ConnectionClosedError
import json
import base64  # [!code ++]



# ✅ 상태 저장 딕셔너리들
client_sessions = {}  # client_id → state 매핑
client_states = {}    # websocket → state 매핑


async def send_text(websocket, message):
    await websocket.send(message)


sound_path = "C:/SoundAssets/ding.wav"


from asgiref.sync import sync_to_async

@sync_to_async
def ensure_mysql_connection():
    from django.db import connection
    from django.db.utils import OperationalError

    try:
        connection.cursor()
    except OperationalError:
        connection.close()


# Django 설정
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.aptitude.settings")
import django
django.setup()

from django.conf import settings
from azure.cognitiveservices.speech import (
    SpeechConfig, SpeechSynthesizer, AudioConfig, ResultReason
)
from azure.cognitiveservices.speech.audio import AudioOutputConfig
from kiosk.models import MenuItem
import openai


@sync_to_async
def get_price_from_db(menu_name):
    try:
        item = MenuItem.objects.get(name=menu_name)
        return float(item.price)
    except MenuItem.DoesNotExist:
        print(f"❌ 메뉴 '{menu_name}'에 대한 가격 정보를 찾을 수 없습니다.")
        return 0  # 기본값 처리

openai.api_key = settings.OPENAI_API_KEY

AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION

connected_clients = set()
client_states = {}

def is_positive(text):
    text = text.strip().lower()
    positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ", "좋습니다", "그렇죠", "네네", "예스", "예쓰", "yes", "응응", "엉", "근데", "에", "이때"]

    # 완전 일치
    if text in positive_words:
        return True

    # 마지막 1~3글자가 긍정어로 끝나는 경우
    for word in positive_words:
        if text.endswith(word):
            return True

    return match_fuzzy(text, positive_words)

def is_negative(text):
    negative_words = ["아니", "싫어", "안돼", "노", "그만", "아니요", "안할래"]
    return any(word in text for word in negative_words) or match_fuzzy(text, negative_words)

def match_fuzzy(text, candidates):
    for word in candidates:
        ratio = difflib.SequenceMatcher(None, text, word).ratio()
        if ratio > 0.6:
            return True
    return False

def has_order_intent(text):
    order_keywords = ["주세요", "주문", "먹고", "마시고", "갖고", "주라", "하고", "시킬게", "시키고", "줘", "할래"]
    return any(k in text for k in order_keywords)
    

def play_ding(should_play=True):
    if should_play:
        playsound(sound_path)

# [!code block:start]
async def synthesize_speech(text, websocket=None, activate_mic=True):
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    # 서버에서 소리가 나지 않도록 None으로 설정하여 메모리로 음성 데이터를 받습니다.
    audio_config = None
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    result = synthesizer.speak_text_async(text).get()

    if result.reason == ResultReason.SynthesizingAudioCompleted:
        # 음성 데이터를 base64로 인코딩
        audio_bytes = result.audio_data
        b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
        
        # WebSocket으로 오디오 데이터 전송
        if websocket:
            try:
                # activate_mic 정보도 함께 보내 클라이언트가 mic_on을 보낼지 결정하도록 합니다.
                await websocket.send(json.dumps({"type": "tts_audio", "data": b64_audio, "activate_mic": activate_mic}))
                print("✅ TTS 오디오 데이터 전송 성공")
            except Exception as e:
                print(f"⚠️ TTS 오디오 데이터 전송 중 오류: {e}")

    return result.reason == ResultReason.SynthesizingAudioCompleted
# [!code block:end]


def clean_input(text):
    original_text = text  # 백업
    original_cleaned = text.strip().lower()


    text = re.sub(r"[^\w가-힣]", "", text)
    text = text.replace(" ", "").lower()
    # 불필요한 끝말 제거 (예: 선택해주세요, 말씀해주세요 등)
    system_phrases = ["선택해주세요", "말씀해주세요", "대답해주세요", "해주세요"]
    for phrase in system_phrases:
        if text.endswith(phrase):
            text = text[: -len(phrase)]

    question_prefixes = [
        "음성으로주문하시겠습니까", "음성주문을시작합니다", "어떤메뉴를원하세요",
        "다시메뉴를말씀해주세요", "다시말씀해주세요",
        "같은옵션으로주문할까요", "옵션을진행할까요", "아메리카노다시주문하시겠어요", "사 추가하시겠습니까?",
        "같은옵션으로주문할까요네또는아니요로말씀해주세요",  # 완전한 문장도 포함
        "옵션을진행할까요네또는아니요로말씀해주세요", "4 추가하시겠습니다 ", "동일한 옵션으로 하나 더 담을까요", "추가 주문 여부를 다시 말씀해 주세요", "메뉴 있으신가요", "음성으로주문하시겠습니다", "차 추가하시겠습니까", "사추가여부를다시", "사추가 여부를 다시 말씀해 주세요", "사 추가하시겠습니다", "큰 사이즈는 500원이 추가됩니다", "2,500원입니다", "어떤 메뉴를 원하세요", "간단한 식사 대용으로도 좋습니다", "큰 사이즈는 500원이 추가됩니다", "결제를 진행할까요", "결제를 진행할까요?", "있으신가요"
    ]
    
    # ✅ 시스템 질문 유사 시작문 제거
    for _ in range(3):
        for phrase in question_prefixes:
            if text.startswith(phrase):
                print(f"🔍 시스템 문장 제거됨: {phrase}")
                text = text[len(phrase):]

    # ✅ 끝 문장도 잘라내기
    SYSTEM_SUFFIXES = [
        "네또는아니요로대답해주세요",
        "다시말씀해주세요네",
        "네또는아니요로말씀해주세요",
        "네또는아니요로답해주세요"
    ]
    for suffix in SYSTEM_SUFFIXES:
        if text.endswith(suffix):
            print(f"🔚 끝 문장 제거됨: {suffix}")
            text = text[: -len(suffix)]

    # ✅ 만약 제거 후 비어 있고, 원본도 시스템 질문이면 무시 (빈 텍스트 반환)
    if not text.strip():
        all_phrases = question_prefixes + SYSTEM_SUFFIXES
        for p in all_phrases:
            if original_cleaned.startswith(p) or original_cleaned.endswith(p):
                print(f"🛑 입력이 시스템 문장으로만 구성됨 → 무시 대상")
                return ""
        # 그렇지 않다면 원본 유지
        return original_text

    # ✅ 흔한 패턴 정리
    system_phrases = ["선택해주세요", "말씀해주세요", "대답해주세요", "해주세요"]
    for phrase in system_phrases:
        if text.endswith(phrase):
            text = text[: -len(phrase)]


    for j in ["을", "를", "이", "가", "은", "는", "에서", "로", "으로", "도", "만", "께", "한테", "에게", "랑", "하고"]:
        if text.endswith(j):
            text = text[:-len(j)]
            break
    return text



def strip_gpt_response_prefix(text, last_gpt_reply):
    if not last_gpt_reply:
        return text
    gpt_clean = clean_input(last_gpt_reply)
    text_clean = clean_input(text)

    if text_clean.startswith(gpt_clean[:20]):  # 앞 20자 유사성 검사
        print("🔍 GPT 응답 앞부분 포함 → 제거 시도")
        return text_clean.replace(gpt_clean, "").strip()
    return text

def fuzzy_remove_question(cleaned_text, last_question):
    if not last_question or len(cleaned_text) <= 2:
        return cleaned_text  # ➤ 응답이 짧으면 제거하지 않음

    q_cleaned = clean_input(last_question)
    ratio = SequenceMatcher(None, cleaned_text, q_cleaned).ratio()

    if ratio > 0.85 and q_cleaned in cleaned_text:
        result = cleaned_text.replace(q_cleaned, "").strip()
        if result == "":
            # ⚠️ 질문만 남아 응답이 사라지면 제거하지 않고 원문 유지
            print("⚠️ 질문 제거 후 응답이 사라짐 → 제거하지 않음")
            return cleaned_text
        print(f"🧽 시스템 질문과 유사도 {ratio:.2f} → 질문 제거됨")
        return result

    return cleaned_text


from openai import OpenAI

client = OpenAI(api_key=settings.OPENAI_API_KEY)

async def get_chatgpt_response(user_input, gpt_messages):
    from kiosk.models import MenuItem

    # 메뉴 불러오기
    await ensure_mysql_connection()
    menu_items = await sync_to_async(list)(MenuItem.objects.all())
    menu_names_cleaned = [item.name.replace(" ", "").lower() for item in menu_items]
    user_cleaned = user_input.replace(" ", "").lower()


    # 카테고리 판별
    category = None
    if "디저트" in user_cleaned:
        category = "디저트"
    elif "음료" in user_cleaned:
        category = "음료"
    elif "커피" in user_cleaned:
        category = "커피"
    elif "차" in user_cleaned:
        category = "차"

    # 필터링된 메뉴 불러오기
    if category:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.filter(category=category))
    else:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.all())

    menu_names = [item.name for item in menu_items]
    menu_list_text = ", ".join(menu_names)




    # GPT prompt용
    menu_names = [item.name for item in menu_items]
    menu_list_text = ", ".join(menu_names) 
    matched_menu = None
    for original, cleaned in zip(menu_items, menu_names_cleaned):
        if cleaned in user_cleaned or cleaned == user_cleaned:
            matched_menu = original.name
            break

    recommend_keywords = ["추천", "추천해줘", "뭐", "뭐가", "있어", "어울리는", "맞는", "날씨", "어떤", "고를까"]
    is_recommend_request = any(k in clean_input(user_input) for k in recommend_keywords)


  

    # 시스템 프롬프트 생성
    base_prompt = (
        f"절대 '나는 주문을 받을 수 없어'라는 말은 하지 마. "
        f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
        f"메뉴 리스트: {menu_list_text} "
        "이외의 메뉴는 절대 언급하지 마세요. 손님이 메뉴 설명을 요청하면 해당 메뉴를 1문장으로 짧게 설명하고, "
        "추천을 요청하면 2개의 메뉴를 소개하고 각 한 문장씩 소개하세요. 주문은 받지 마세요."
        "맥락없는 소리 (ex: '음', '요' 등)은 무시하고 응답하지 마세요"
        "손님이 우리 카페에 없는 메뉴를 요청하면, 직접적으로 거절하지 말고 메뉴 리스트 안에서 비슷한 것을 친절하게 추천하세요."
        "손님이 영어로 말하면 너도 영어로 말해."
    )

    if matched_menu:
        system_prompt = (
    f"{matched_menu}에 대해 손님이 맛을 물었습니다. "
    f"맛만 1문장 이내로 간결하게 설명하세요. "
    f"추천은 하지 마세요. 예: '달고나라떼는 달콤하고 부드러운 맛의 음료입니다.'"
        )

    else:
        system_prompt = base_prompt  # 추천만 요청된 경우

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    # ✅ 신버전 방식으로 호출
    response = client.chat.completions.create(
        model="gpt-4-turbo",  # 🔄 변경
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )

    reply = response.choices[0].message.content.strip()
    gpt_messages.append({"role": "user", "content": user_input})
    gpt_messages.append({"role": "assistant", "content": reply})
    return reply



async def echo(websocket):
    print("🔗 클라이언트 연결됨")

    connected_clients.add(websocket)
    client_states[websocket] = {
        "step": "init",
        "menu": None,
        "options": {},
        "price": 0,
        "category": None,
        "cart": [],
        "finalized": False,
        "first_order_done": False,
        "gpt_messages": []
    }
    state = client_states[websocket]

    try:
        while True:
            if state.get("finalized"):
                await asyncio.sleep(1)
                continue

            if state["step"] == "waiting_additional_retry":
                cleaned = cleaned_text.strip().lower()
                print(f"📨 받은 메시지: {cleaned_text}, 현재 상태: {state['step']}, is_negative: {is_negative(cleaned)}")

                if is_positive(cleaned):
                    await websocket.send("mic_off")
                    response_text = "어떤 메뉴를 원하세요?"
                    await synthesize_speech(response_text, websocket, activate_mic=True)
                    state["step"] = "await_menu"
                    continue

                elif is_negative(cleaned):
                    if state.get("path") == "/start":
                        await websocket.send("set_resume_flag")

                    await send_text(websocket, "go_to_pay")
                    state["step"] = "confirm_payment"

                    # 💳 주문 요약 및 결제 멘트 생성 (기존 코드 복사해서 재사용)
                    from collections import defaultdict
                    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})
                    for item in state["cart"]:
                        size = item["options"].get("size")
                        temp = item["options"].get("temp")
                        shot = item["options"].get("shot")
                        

                        opt_parts = []
                        if size:
                            opt_parts.append("사이즈 큰 거" if size == "큰" else f"사이즈 {size}")
                        if temp:
                            opt_parts.append(temp)
                        if shot:
                            opt_parts.append("샷 없음" if shot == "없음" else shot)

                        opt_text = ", ".join(opt_parts)
                        key = f"{item['name']}|{opt_text}"

                        counter[key]["count"] += 1
                        counter[key]["total_price"] += item["price"]
                        counter[key]["name"] = item["name"]
                        counter[key]["options"] = opt_text

                    summary = "주문 내역입니다:\n"
                    total = 0
                    
                    for item in state.get("cart", []):
                        name = item.get("name", "")
                        options = item.get("options", {})
                        count = item.get("count", 1)
                        base_price = await get_price_from_db(name)
                        
                        # ✅ 옵션 기반 추가 가격 계산
                        extra_price = 0
                        size = options.get("size")
                        shot = options.get("shot")

                        if size == "큰":
                            extra_price += 500
                        if shot == "1샷":
                            extra_price += 300
                        elif shot == "2샷":
                            extra_price += 600

                         

                        total_price = (base_price + extra_price) * count
                        item["price"] = base_price + extra_price  # ✅ 단가 갱신
                        item["total_price"] = total_price         # ✅ 총액 갱신

                        option_text = ", ".join([f"{k}: {v}" for k, v in options.items()])
                        summary += f"- {name} {option_text} {count}개에 {total_price:,}원\n"
                        total += total_price

                    final_prompt = f"{summary.strip()}\n총 결제 금액은 {total}원입니다.\n."


                    print("📤 cart_summary 텍스트 전송 중:", final_prompt)
                    await websocket.send(json.dumps({
                        "type": "cart_summary",
                        "text": final_prompt
                    }))
                    print("📤 cart_summary 전송 완료:", final_prompt)

                    state["step"] = "confirm_payment"
                    state["last_question"] = final_prompt
                    state["cart_summary"] = final_prompt

       
                    await websocket.send("go_to_pay")
                    await websocket.send("mic_off")  # ✅ 순서상 늦어도 여전히 필요
                    await synthesize_speech(final_prompt, websocket, activate_mic=True)
                
                    continue



                # ❌ 아직도 인식 못했을 경우 → 대기 유지
                elapsed = time.time() - state.get("additional_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "추가 주문 여부를 다시 말씀해주세요."
                    state["step"] = "confirm_additional"
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket)
                
                await asyncio.sleep(1)
                continue

            if state["step"] == "waiting_shot_retry":
                elapsed = time.time() - state.get("shot_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "샷 추가 여부를 다시 말씀해주세요. 네 또는 아니요로 대답해 주세요."
                    state["step"] = "ask_shot"
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                await asyncio.sleep(1)
                continue

            if state["step"] == "waiting_size_retry":
                elapsed = time.time() - state.get("size_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "사이즈를 다시 말씀해주세요. 보통 또는 큰 사이즈 중 하나를 선택해주세요."
                    state["step"] = "choose_size"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                await asyncio.sleep(1)
                continue
            
            if state["step"] == "waiting_temp_retry":
                elapsed = time.time() - state.get("temp_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "온도를 다시 말씀해주세요. 따듯한 것 또는 차가운 것로 대답해 주세요."
                    state["step"] = "choose_temp"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                await asyncio.sleep(1)
                continue

            message = await websocket.recv()
            text = message.strip()


            print(f"📨 받은 메시지: {text}")
            print(f"🔁 요청 시점 websocket id: {id(websocket)}") 

            if text == "request_mic_on":
                print(f"🔁 클라이언트로부터 mic_on 요청 수신 → 전송 시도")
                if websocket.close_code is not None:
                    print("❌ mic_on 요청 수신 → 하지만 WebSocket이 이미 닫힘")
                else:
                    print("🔁 클라이언트로부터 mic_on 요청 수신 → 전송")
                    await websocket.send("mic_on")
                continue

            elif message == "read_cart":
                print("📥 read_cart 요청 수신됨")

                items = []
                total = 0

                for item in state.get("cart", []):  # ✅ cart에서 바로 꺼냄
                    name = item.get("name")
                    price = item.get("total_price", 0)
                    options = item.get("options", {})
                    count = item.get("count", 1)  # ✅ count 없으면 기본값 1로

                    base_price = await get_price_from_db(name)

                    # ✅ 옵션에 따른 추가 금액 계산
                    extra_price = 0
                    size = options.get("size")
                    shot = options.get("shot")
                                        
                    if size == "큰":
                        extra_price += 500
                    if shot == "1샷":
                        extra_price += 300
                    elif shot == "2샷":
                        extra_price += 600

                    final_price = base_price + extra_price
                    total_price = final_price * count

                    # ✅ cart 내부에도 다시 반영
                    item["price"] = final_price
                    item["total_price"] = total_price

                    # ✅ 전달할 JSON 항목 구성
                    items.append({
                        "name": name,
                        "count": count,
                        "price": final_price
                    })

                    total += total_price

                    await websocket.send(json.dumps({
                        "type": "cart_items",
                        "items": items
                    }, default=str))
                    print("📤 cart_items 전송 완료:", items)

    
            try:
                data = json.loads(message)

                if data.get("type") == "page_info":
                    client_id = data.get("client_id")
                    path = data.get("path")
                    state["client_id"] = client_id 
                    state["path"] = path  # ✅ 여기에 경로 저장
                    
                    print(f"📄 클라이언트 페이지 경로: {path}, client_id: {client_id}")
                    

                    if path == "/order":

                        # ✅ disable_voice가 True면 mic_on 보내지 않음
                        if state.get("disable_voice"):
                            print("🚫 disable_voice 플래그로 인해 mic_on 전송 생략")
                        else:
                            await websocket.send("mic_on")

                    # client_id로 상태 복원 또는 새로 생성
                    if client_id in client_sessions:
                        print("🔁 기존 상태 복원")
                        state = client_sessions[client_id]
                    else:
                        print("🆕 새 상태 생성")
                        state = {
                            "step": "init",
                            "menu": None,
                            "options": {},
                            "price": 0,
                            "category": None,
                            "cart": [],
                            "finalized": False,
                            "first_order_done": False,
                            "gpt_messages": [],
                        }
                        client_sessions[client_id] = state
                    
                    state["path"] = path

                    client_states[websocket] = state
                    continue  # 다음 메시지로 넘어가기

            except json.JSONDecodeError:
                pass  # 일반 메시지는 아래에서 처리

            # 그 외 일반 텍스트 메시지 처리
            state = client_states.get(websocket)
            if not state:
                continue

            cleaned_text = message.strip().replace(" ", "")

            if is_negative(cleaned_text) and state.get("step") == "confirm_voice_order":
                state["disable_voice"] = True
                await websocket.send("set_disable_voice")
                print("🚫 사용자가 아니요 응답 → disable_voice 설정 완료")
                continue

            cleaned_text = message.strip()

        


            
            # ✅ 항상 초기화
            cleaned_text = clean_input(text)
            cleaned_text = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))
            last_gpt_reply = state["gpt_messages"][-1]["content"] if state["gpt_messages"] else ""
            cleaned_text = strip_gpt_response_prefix(cleaned_text, last_gpt_reply)



            if text == "resume_from_menu":
                print("🔁 클라이언트 재연결 → 메뉴 선택 상태로 복원됨")
                state["step"] = "await_menu"
                response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
                await synthesize_speech(response_text, websocket, activate_mic=True)
                continue

            elif text == "request_summary_tts":
                prompt = state.get("cart_summary")
                if prompt:
                    await websocket.send("mic_off")
                    await synthesize_speech(prompt, websocket, activate_mic=True)
                continue  # 다른 메시지 처리 안 하도
            

            elif text == "resume_from_pay":
                print("🔁 pay_all 복귀 요청 수신 → 장바구니 요약 및 결제 질문 재출력")

                # 결제 직전 상태로 복원
                state["step"] = "confirm_payment"

                # 저장된 장바구니 요약 및 질문 불러오기
                summary = state.get("cart_summary", "")
                if summary:
                    await synthesize_speech(summary.strip(), websocket, activate_mic=False)

                followup = state.get("last_question", "총 결제 금액은 ~원입니다. ")
                await synthesize_speech(followup.strip(), websocket, activate_mic=True)


            if text == "start_order":
                state.update({
                    "step": "await_start",
                    "cart": [],
                    "finalized": False,
                    "first_order_done": False,  # 필요 시 초기화
                    "menu": None,
                    "options": {},
                    "price": 0,
                    "category": None, 
                    "count": 1
                })
                # ✅ 위의 3단계 코드 삽입
                await websocket.send("mic_off")
                await synthesize_speech("음성으로 주문하시겠습니까?", websocket, activate_mic=False)
                threading.Thread(target=play_ding).start()
                await asyncio.sleep(0.1)
                await synthesize_speech("소리 이후에 말씀해주세요.", websocket, activate_mic=False)
                
                # 4. 약간 쉬었다가 (사용자 준비 시간 줌)
                await asyncio.sleep(0.2)

                # 5.음성 주문을 시작합니다.띵 소리 2 (→ 마이크 ON 유도)
                threading.Thread(target=play_ding).start()
                await asyncio.sleep(0.05)
                await websocket.send("mic_on")
                
                continue



            
            if state["step"] == "await_start":
                cleaned_text = clean_input(text)
                cleaned_text = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))
                last_gpt_reply = state["gpt_messages"][-1]["content"] if state["gpt_messages"] else ""
                cleaned_text = strip_gpt_response_prefix(cleaned_text, last_gpt_reply)
                
                print(f"🧾 받은 cleaned_text: {cleaned_text}")
                print(f"🧭 현재 상태: {state['step']}")

                if is_positive(cleaned_text):
                    await websocket.send("goto_menu")  # 🚀 이동만 처리
                    await asyncio.sleep(0.3)  # 💡 약간 대기 (클라이언트 연결 안정화)
                    continue


                # 🔒 빈 입력 무시
                if not cleaned_text.strip():
                    print(f"⚠️ 빈 입력 무시: '{cleaned_text}'")
                    continue
                
                # 마지막 catch-all fallback 처리 전에 추가
                if state["step"] == "announce_menu_prompt":
                    print("🛑 announce_menu_prompt 상태 → 입력 무시")
                    continue

         
                # 의미 없는 단일 음절들 (직접 확정 가능)
                short_ignore = ["오", "우", "이", "흠", "요"]
                if cleaned_text in short_ignore:
                    print(f"⚠️ 의미 없는 단어 무시: '{cleaned_text}'")
                    continue



                if SequenceMatcher(None, cleaned_text, clean_input(last_gpt_reply)).ratio() > 0.9:
                    print("⚠️ GPT 응답과 유사한 입력 → 무시")
                    continue


                print(f"🧹 정제된 텍스트: '{cleaned_text}'")
                print(f"🧭 현재 상태: {state['step']}")



                if not cleaned_text:
                    continue

            response_text = ""

            if state["step"] == "await_start":

                if is_positive(cleaned_text):
                    response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
                    await synthesize_speech(response_text, websocket, activate_mic=False)

                    await asyncio.sleep(0.8)  # TTS 끝난 뒤 약간 대기

                    await websocket.send("goto_menu")  # ✅ 클라이언트가 이미 이걸 처리하도록 되어 있음
                    state["step"] = "await_menu"
                    continue



                elif is_negative(cleaned_text):  # 사용자가 "아니요"라고 응답한 경우
                    response_text = "일반 키오스크로 진행하세요."
                    await synthesize_speech(response_text, websocket, activate_mic=False)

                    # ✅ 0.5초~1초 대기 후 페이지 이동 신호 전송
                    await asyncio.sleep(0.7)

                    await websocket.send("set_disable_voice")
                    await asyncio.sleep(0.1)
                    await websocket.send("go_to_order2")
                    print("📤 go_to_order2 메시지 전송됨")

              
                    client_states.pop(websocket, None)
                    continue


            elif state["step"] == "await_menu":
                await ensure_mysql_connection()
                menu_items = await sync_to_async(list)(MenuItem.objects.all())

                cleaned_user_text = cleaned_text.replace(" ", "").lower()


                matched_item = next(
                    (item for item in menu_items if item.name.replace(" ", "").lower() in cleaned_user_text),
                    None
                )



                def is_order_expression(text):
                    order_phrases = [
                        "주세요", "주문할게요", "시킬게요", "갖고갈게요",
                        "먹을게요", "살게요", "할게요", "줘", "주라", "줄래",
                        "도하나주세요", "하나주세요", "더주세요"
                    ]
                    
                    text_clean = text.replace(" ", "").lower()
                    
                    for phrase in order_phrases:
                        if phrase in text_clean:
                            return True
                        if difflib.SequenceMatcher(None, text_clean, phrase).ratio() > 0.7:
                            return True
                    return False
                

                def is_repeat_order(text):
                    repeat_keywords = [
                        "같은걸로", "같은거", "그걸로", "그거", "방금", "또하나", "하나더", "다시",
                        "같은거하나더", "같은메뉴", "아까", "한번더", "이전주문", "전에주문한거", "이전과같은"
                    ]

                    text_clean = text.replace(" ", "").lower()
                    return any(k in text_clean for k in repeat_keywords)




                cleaned_user_text = cleaned_text


                print("🕵️ 반복 주문 감지 여부:", is_repeat_order(cleaned_user_text))

                if is_repeat_order(cleaned_user_text):
                    if state["cart"]:
                        last_item = state["cart"][-1]
                        # 여기서 category를 DB에서 가져옴
                        try:
                            item_obj = await sync_to_async(MenuItem.objects.get)(name=last_item["name"])
                            category = item_obj.category
                        except MenuItem.DoesNotExist:
                            category = "기타"


                        state["last_repeat_item"] = {
                            **last_item,
                            "category": category
                        }
                        response_text = f"{last_item['name']} 다시 주문하시겠어요? 이전과 동일한 옵션으로 하나 더 담을까요?"
                        state["step"] = "confirm_repeat_options"
                    else:
                        response_text = "이전에 주문한 메뉴가 없어요. 다시 메뉴를 말씀해주세요."
                    
                    
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue


                has_clear_order = is_order_expression(cleaned_user_text)


                # "아메리카노" 같이 메뉴 단독 발화인 경우 허용
                is_exact_menu = matched_item and matched_item.name.replace(" ", "").lower() == cleaned_user_text

                has_clear_order = is_order_expression(cleaned_user_text)
                print("🧪 유사도 기반 매칭:", matched_item.name if matched_item else None)
                print("📌 주문 표현:", has_clear_order, "| 정확 메뉴:", is_exact_menu)


                if matched_item and (has_clear_order or is_exact_menu):
                    item = matched_item
                    state.update({
                        "menu": item.name,
                        "price": int(item.price),
                        "category": item.category,
                        "options": {},
                        "count": 1
                    })
                    if item.category == "디저트":
                        state["cart"].append({"name": item.name, "options": {}, "price": state["price"], "total_price": item.price})
                        response_text = f"{item.name} {state['price']}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요? 네 또는 아니요로 대답해주세요"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        response_text = f"{item.name} {state['price']}원입니다. 옵션 선택을 진행할까요?"
                        state["step"] = "confirm_options"
                        await websocket.send("mic_off")            # 🔇 먼저 마이크 끄기
                        await websocket.send(response_text)         # 📩 텍스트 응답 보내기
                        await synthesize_speech(response_text, websocket, activate_mic=True)  # 🔊 실제 TTS + 띵 → mic_on
                else:
                    # GPT로 질문 위임
                    gpt_reply = await get_chatgpt_response(text, state["gpt_messages"])
                    await websocket.send("mic_off")  # 🎤 응답 전에 먼저 마이크 끔
                    await websocket.send(gpt_reply)
                    await synthesize_speech(gpt_reply, websocket)  # 🔊 응답 말하고 띵 → 마이크 켜짐




            elif state["step"] == "confirm_repeat_options":
                print("🧪 confirm_repeat_options 단계 진입")
                print("🧪 응답 텍스트:", cleaned_text)

            # 💬 시스템 질문이 다시 들어온 경우 → 무시
                if cleaned_text.strip() in ["같은옵션으로주문할까요"]:
                    print("⚠️ 시스템 질문만 재인식됨 → 무시")
                    continue

                if is_positive(cleaned_text.strip()):
                    item = state.get("last_repeat_item")
                    if item:
                        print("🧾 마지막 주문 옵션 복사:", item)
                        
                        if item["category"] == "디저트":
                            # ✅ 디저트는 옵션 없이 1번만 담기
                            state["cart"].append({
                                "name": item["name"],
                                "options": {},
                                "price": item["price"], 
                                "total_price": item.price,
                                "count": 1

                            })
                            response_text = f"{item['name']}을 담았습니다. 추가로 주문하시겠습니까?"
                            await websocket.send("mic_off")  # ✅ 여기에 추가
                            await synthesize_speech(response_text, websocket, activate_mic=True)  # 마이크는 synthesize_speech가 
                            state["step"] = "confirm_additional"

                        else:
                            # ✅ 그 외는 기존 옵션 복사
                            state["cart"].append({
                                "name": item["name"],
                                "options": item["options"].copy(),
                                "total_price": item.price,
                                "price": item["price"]
                            })
                            response_text = f"{item['name']}을(를) 동일한 옵션으로 하나 더 담았습니다. 추가로 주문하시겠습니까?"
                            await websocket.send("mic_off")  # ✅ 여기에 추가
                            await synthesize_speech(response_text, websocket, activate_mic=True)  # 마이크는 synthesize_speech가 
                            state["step"] = "confirm_additional"

                        state.update({
                            "step": "confirm_additional",
                            "menu": None,
                            "options": {},
                            "price": 0
                        })



                elif is_negative(cleaned_text.strip()):
                    # 이전 메뉴는 유지하지만 옵션만 다시 고를 수 있도록 설정
                    repeat_item = state.get("last_repeat_item")
                    if repeat_item:
                        state["menu"] = repeat_item["name"]
                        state["category"] = repeat_item.get("category") or state.get("category")
                        
                        # 가격은 기본 가격으로 초기화 (옵션가 제외)
                        try:
                            item_obj = await sync_to_async(MenuItem.objects.get)(name=repeat_item["name"])
                            state["price"] = int(item_obj.price)
                            state["category"] = item_obj.category
                        except MenuItem.DoesNotExist:
                            state["price"] = repeat_item.get("price", 0)

                    # 옵션 선택 단계로 이동 (단, 디저트는 옵션 없이 바로 담기)
                    if state["category"] == "디저트":
                        state["cart"].append({
                            "name": state["menu"],
                            "options": {},
                            "price": state["price"],
                            "total_price": item.price,
                            "count": 1
                        })
                        response_text = f"{state['menu']}을 담았습니다. 추가로 주문하시겠습니까?"
                        await websocket.send("mic_off")  # ✅ 여기에 추가
                        await synthesize_speech(response_text, websocket, activate_mic=True)  # 마이크는 synthesize_speech가 
                        state["step"] = "confirm_additional"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        # 음료/커피/차 등은 옵션 선택
                        if state["category"] in ["커피", "음료", "차"]:
                            response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                            state["step"] = "choose_size"
                        else:
                            response_text = "다시 옵션을 선택해주세요."
                            state["step"] = "confirm_options"



                else:
                    # 유효하지 않은 응답이거나 시스템 질문 포함된 채 인식됨 → 재질문
                    response_text = "같은 옵션으로 주문할까요? 네 또는 아니요로 말씀해주세요."
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue



            elif state["step"] == "confirm_options":
                if is_positive(cleaned_text):
                    response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                    state["step"] = "choose_size"
                    await websocket.send("mic_off")  # 🔇 먼저 끄고
                    await websocket.send(response_text)  # 💬 텍스트 응답
                    await synthesize_speech(response_text, websocket, activate_mic=True)  # 🔊 출력 + 지연 마이크 ON
                    continue  # ✅ 빠져나가기
                elif is_negative(cleaned_text):
                    category = state["category"]
                    if category in ["커피", "음료"]:
                        state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
                    elif category == "차":
                        state["options"] = {"size": "보통", "temp": "아이스"}
                    else:
                        state["options"] = {}
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"], "total_price": item.price})
                    response_text = f"기본 옵션으로 {state['menu']}를 장바구니에 담았습니다. 추가로 주문하시겠습니까? 네 또는 아니요로 대답해주세요"
                    await websocket.send("mic_off")  # ✅ 시스템 발화 전 마이크 끄기
                    await synthesize_speech(response_text, websocket, activate_mic=True)  # 🔈 TTS 출력 후 띵 소리 + 마이크 재개
                    
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    response_text = None



                else:
                    response_text = "옵션을 진행할까요? 네 또는 아니요로 말씀해주세요."

            elif state["step"] == "choose_size":
                if "큰" in cleaned_text:
                    state["options"]["size"] = "큰"
                    state["price"] += 500
                elif "보통" in cleaned_text or "기본" in cleaned_text:
                    state["options"]["size"] = "보통"
                else:
                    # 유효하지 않은 사이즈 응답 → 재질문 대기 상태로 전환
                    state["step"] = "waiting_size_retry"
                    state["size_prompt_time"] = time.time()
                    continue

                if state["category"] == "음료":
                    state["options"]["temp"] = "아이스"
                    response_text = "샷 추가하시겠습니까?"
                    state["step"] = "ask_shot"
                else:
                    response_text = "따듯한 것 또는 차가운 것 중 선택해주세요."
                    state["step"] = "choose_temp"
                    state["last_question"] = response_text 
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue  

            elif state["step"] == "choose_temp":
                if any(t in cleaned_text for t in ["아이스", "차가운", "찬거", "찬 거", "시원한", "시원"]):
                    state["options"]["temp"] = "아이스"
                elif any(t in cleaned_text for t in ["핫", "하트", "하", "하스", "합", "뜨거운", "따뜻한", "드거운", "다듯한", ]):
                    state["options"]["temp"] = "핫"
                else:
                    # 유효하지 않은 응답 → 재질문 대기 상태로 전환
                    state["step"] = "waiting_temp_retry"
                    state["temp_prompt_time"] = time.time()
                    continue

                if state["category"] == "차":
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"], "total_price": item.price})
                    response_text = f"추가 메뉴 있으신가요?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                else:
                    response_text = "샷 추가하시겠습니까?"
                    state["step"] = "ask_shot"
                    state["last_question"] = response_text  # ❗️이거 추가
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue


            elif state["step"] == "ask_shot":
                if "아니" in cleaned_text:
                    state["options"]["shot"] = "없음"
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"], "total_price": item.price})
                    response_text = f"추가 메뉴 있으신가요?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})


                elif is_positive(cleaned_text):
                    response_text = "1번 추가는 +300원이고 2번 추가는 +600원입니다."
                    state["step"] = "choose_shot"
                    state["last_question"] = response_text  # 추가
                    print("✅ 샷 추가 긍정 응답 → choose_shot로 전환")
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue

                
                else:
                    state["step"] = "waiting_shot_retry"
                    state["shot_prompt_time"] = time.time()
                    continue

        
            elif state["step"] == "choose_shot":
                if any(x in cleaned_text for x in ["2", "두"]):
                    state["options"]["shot"] = "2샷"
                    state["price"] += 600
                elif any(x in cleaned_text for x in ["1", "한"]):
                    state["options"]["shot"] = "1샷"
                    state["price"] += 300
                else:
                    # 🔁 유효하지 않은 응답이면 다시 묻기
                    state["step"] = "waiting_shot_retry"
                    state["shot_prompt_time"] = time.time()
                    continue

                state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"], "total_price": item.price})
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})




            elif state["step"] in ["confirm_additional", "waiting_confirm_additional"]:
                cleaned = cleaned_text.strip().lower()
                

                print(f"📨 받은 메시지: {cleaned_text}, 현재 상태: {state['step']}, is_negative: {is_negative(cleaned)}")

                if is_positive(cleaned_text):
                    await websocket.send("mic_off")  # ✅ 마이크를 먼저 꺼준다
                    response_text = "어떤 메뉴를 원하세요?"
                    await synthesize_speech(response_text, websocket, activate_mic=True)  # 띵 + 다시 켜짐
                    state["step"] = "await_menu"
                    continue


                elif is_negative(cleaned_text):
                    if state.get("path") == "/start":  # ✅ 여기서 안전하게 참조
                        await websocket.send("set_resume_flag")

                    await send_text(websocket, "go_to_pay")
                    state["step"] = "confirm_payment"

                    from collections import defaultdict

                    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})
                    

                    for item in state["cart"]:
                        size = item["options"].get("size")
                        temp = item["options"].get("temp")
                        shot = item["options"].get("shot")

                        opt_parts = []
                        if size:
                            opt_parts.append("사이즈 큰 거" if size == "큰" else f"사이즈 {size}")
                        if temp:
                            opt_parts.append(temp)
                        if shot:
                            opt_parts.append("샷 없음" if shot == "없음" else shot)

                        opt_text = ", ".join(opt_parts)
                        key = f"{item['name']}|{opt_text}"

                        counter[key]["count"] += 1
                        counter[key]["total_price"] += item["price"]
                        counter[key]["name"] = item["name"]
                        counter[key]["options"] = opt_text

                    # 1️⃣ 내역 요약
                    from collections import defaultdict
                    summary = "주문 내역입니다:\n"
                    total = 0
                    for item in counter.values():
                        summary += f"- {item['name']} {item['options']}  {item['count']}개에 {item['total_price']}원\n"
                        total += item["total_price"]

                    # 2️⃣ 결제 질문
                    final_prompt = f"{summary.strip()}\n총 결제 금액은 {total}원입니다."

                    state["step"] = "confirm_payment"
                    state["last_question"] = final_prompt
                    state["cart_summary"] = final_prompt

                    print("📤 cart_summary 텍스트 전송 중:", final_prompt)
                    await websocket.send(json.dumps({
                        "type": "cart_summary",
                        "text": final_prompt
                    }))
                    print("📤 cart_summary 전송 완료:", final_prompt)
                                        

                    # 마이크 끄고 멘트 출력
                    await websocket.send("go_to_pay")
                    await websocket.send("mic_off")
                    await synthesize_speech(final_prompt, websocket, activate_mic=True)
                                    
        
                else:
                    # ✅ 8초간 대기 후 재질문
                    state["step"] = "waiting_confirm_additional"
                    state["last_question"] = "추가 주문 여부를 네 또는 아니요로 말씀해주세요."

                    async def delayed_reprompt():
                        await asyncio.sleep(8)
                        if state["step"] == "waiting_confirm_additional":
                            await websocket.send("mic_off")
                            await synthesize_speech(state["last_question"], websocket)

                    asyncio.create_task(delayed_reprompt())

                    
            elif state["step"] in ["confirm_payment", "waiting_payment_retry"]:
                if cleaned_text in ["pay_all_ready", "read_cart", "request_mic_on"]:
                    print(f"⚠️ 시스템 메시지 무시됨: {cleaned_text}")
                    continue

                cleaned = fuzzy_remove_question(cleaned_text, state.get("last_question", "")).strip().lower()
                
                print(f"🧼 원본 응답: {cleaned_text}")
                print(f"🧹 정제 후 응답: {cleaned}")
                print(f"✅ 긍정 인식 여부: {is_positive(cleaned)}")

                if is_positive(cleaned) and state["step"] in ["confirm_payment", "waiting_payment_retry"]:
                    print("💳 결제 확정 → 팝업 실행")
                    state["step"] = "payment_in_progress"

                    try:
                        await websocket.send("popup_payment")  # 💳 클라이언트에 팝업 명령 전송
                        print("📨 popup_payment 메시지 전송됨")
                    except Exception as e:
                        print(f"❌ popup_payment 전송 실패: {e}")

                    print("📨 popup_payment 메시지 전송됨")
                  
                    final_announce = "결제를 진행합니다."
                    await websocket.send(final_announce)
                    await synthesize_speech(final_announce, websocket, activate_mic=False)

                    await asyncio.sleep(5)
                 
                    
                    print("✅ go_to_done 메시지 전송됨")
                    await websocket.send("go_to_done")
                    await asyncio.sleep(1)    
                    

                    # 🔄 상태 초기화
                    state.update({
                        "step": "await_start",
                        "menu": None,
                        "options": {},
                        "price": 0,
                        "category": None,
                        "cart": [],
                        "finalized": False,
                        "first_order_done": False
                    })
                    continue
                    
                    

                
                
                

                elif is_negative(cleaned):
                    if state.get("step") in ["confirm_payment", "waiting_payment_retry"]:
                        # ❌ 상태가 바뀌면 안됨 — 이미 결제 질문 상태니까 유지
                        print("🛑 유저가 결제 거부 → 시작 페이지로 이동")
                        await websocket.send("goto_start")

                        # 🧼 상태 초기화
                        state.update({
                            "step": "await_start",
                            "menu": None,
                            "options": {},
                            "price": 0,
                            "category": None,
                            "cart": [],
                            "finalized": False,
                            "first_order_done": False
        
                        })
                    continue


                else:
                    print(f"📨 수신된 응답: {cleaned}, 현재 상태: {state['step']}, is_positive: {is_positive(cleaned)}")
                    await websocket.send("mic_off")  
                     # ❌ 여기서만 재질문 필요
                    retry_text = "결제를 진행할까요? 네 또는 아니요로 말씀해주세요."
                    state["step"] = "waiting_payment_retry"
                    state["last_question"] = retry_text


                    await websocket.send("mic_off")              # 1. 마이크 끄고
                    await synthesize_speech(retry_text, websocket, activate_mic=False)  # 3. TTS만 실행
                    await asyncio.sleep(0.2)                     # 4. TTS 끝나고도 잠깐 대기
                    await websocket.send("mic_on")  

                    # ⏱️ 8초 후 응답 없으면 재질문
                    async def delayed_payment_retry():
                        await asyncio.sleep(8)
                        if state["step"] == "waiting_payment_retry":
                            print("⏱️ 응답 없음 → 결제 재질문 출력")
                            await asyncio.sleep(1)

                            # ✅ 마지막 질문과 다르면 (= 이미 응답해서 진행 중이면) 재질문 X
                            if state.get("last_question") != retry_text:
                                print("⛔ 상태 변경됨 → 재질문 생략")
                                return
                            
                            await websocket.send("mic_off")
                            await synthesize_speech(retry_text, websocket, activate_mic=True)

                    asyncio.create_task(delayed_payment_retry())
                    continue


            if cleaned_text == "done_page_ready":
                print("✅ done 페이지 준비됨 → 결제 완료 멘트 출력")
                await synthesize_speech("결제가 완료되었습니다. 감사합니다.", websocket, activate_mic=False)
                continue        


            if response_text and state["step"] not in ["confirm_options"]:
                state["last_question"] = response_text
                await websocket.send(response_text)
                await synthesize_speech(response_text, websocket)


    except websockets.ConnectionClosed:
        print("❌ 클라이언트 연결 종료")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        if websocket in client_states:
            client_states.pop(websocket, None)


async def main():
    port = int(os.environ.get("PORT", 8002))  # Railway에서 제공한 PORT를 사용
    async with websockets.serve(echo, "0.0.0.0", port):  # ← 반드시 "0.0.0.0"
        print(f"✅ WebSocket 서버가 {port}번 포트에서 실행 중")
        await asyncio.Future()
    


if __name__ == "__main__":
    asyncio.run(main())



# ddoing11/projectt/projectt-main/kiosk/static/js/voice_socket_main.js
"use strict";

console.log("✅ JS 작동 중입니다");

let socket;
let recognition;
let recognizing = false;
let resumeHandled = false;  // ✅ 상태 복원 응답 후 인식 시작 여부
let isStarting = false; // 🔹 새로 추가




function showPopupWithRetry(retryCount = 10) {
      const popup = document.getElementById("popup-overlay");
      if (popup) {
        popup.style.display = "flex";
        console.log("✅ popup-overlay 표시 완료");
        setTimeout(() => {
          window.location.href = "/done";
        }, 5000);
      } else if (retryCount > 0) {
        console.warn(`❌ popup-overlay 없음 → 재시도 (${11 - retryCount})`);
        setTimeout(() => showPopupWithRetry(retryCount - 1), 100);
      } else {
        console.error("❌ popup-overlay 끝내 찾을 수 없음. 팝업 표시 실패");
      }
    }


function createWebSocket() {
  if (socket && socket.readyState === WebSocket.OPEN) {
    console.warn("⚠️ 이미 연결된 WebSocket 있음. 생략.");
    return;
  }
  // 로컬 테스트 시에는 127.0.0.1의 8002 포트를 사용
  // 배포 시에는 wss://mykiosk8002.jp.ngrok.io 등 실제 서버 주소로 교체
  const wsUrl =
    window.location.hostname === "127.0.0.1" || window.location.hostname === "localhost"
      ? "ws://127.0.0.1:8002"
      : "wss://mykiosk8002.jp.ngrok.io";

  socket = new WebSocket(wsUrl);





  socket.onopen = () => {
    console.log("✅ WebSocket 연결됨");
    console.log("📡 새 WebSocket 연결됨 (path:", window.location.pathname, ")");

    const pagePath = window.location.pathname;

    const clientId = localStorage.getItem("client_id");

    socket.send(JSON.stringify({
      type: "page_info",
      path: window.location.pathname,
      client_id: clientId
    }));


    if (pagePath === "/pay_all") {
      // 연결 안정화 후 관련 메시지 전송
      setTimeout(() => {
        if (socket.readyState === WebSocket.OPEN) {
          console.log("🧾 /pay_all 페이지에서 초기 메시지 전송");
          socket.send("pay_all_ready");
          socket.send("read_cart");

          // 💡 질문 TTS 끝날 즈음에만 요청 (0.5~1초 후)
          setTimeout(() => {
            socket.send("request_mic_on");
          }, 1000);
        }
      }, 200);
    }
  };


  socket.onmessage = (event) => {
    // 💬 cart_summary JSON 처리 먼저 시도

    console.log("📥 WebSocket 메시지 수신:", event.data);  // ✅ 추가
    try {
      const parsed = JSON.parse(event.data);  // 🔧 이 한 줄이 반드시 있어야 함!

      if (parsed.type === "cart_items") {
        const items = parsed.items || [];
        const tableContent = document.getElementById("cart-items");
        if (tableContent) {
          tableContent.innerHTML = items.map(item => `
            <div style="display: flex; justify-content: space-around; padding: 30px 80px; font-size: 42px;">
              <div style="width: 33%; text-align: center;">${item.name}</div>
              <div style="width: 33%; text-align: center;">${item.count}</div>
              <div style="width: 33%; text-align: center;">${Number(item.price).toLocaleString()}원</div>
            </div>
          `).join('');
          console.log("🧾 장바구니 항목 렌더링 완료:", items);

          // ✅ 렌더링 끝난 후 서버에 TTS 요청
          setTimeout(() => {
            if (socket?.readyState === WebSocket.OPEN) {
              socket.send("request_cart_summary");
            }
          }, 300);  // 약간의 여유를 줘도 좋음
        }
        return;
      }
    } catch (e) {
      console.warn("⚠️ JSON 파싱 실패. 일반 메시지 처리 시도:", event.data);
    }
    
    const text = event.data.trim();
    console.log('📩 서버 응답:', text);

    if (text === "popup_payment") {
      console.log("💳 결제 팝업 띄우기");

      const popup = document.getElementById("popup-overlay");
      if (popup) {
        popup.style.display = "block";

        // 8초 후 자동 닫기
        setTimeout(() => {
          popup.style.display = "none";
        }, 8000);
      } else {
        console.warn("❗ 팝업 요소를 찾을 수 없음: popup-overlay");
      }
    }


    

    if (text === "mic_off") {
      console.log("🔇 서버 지시: 마이크 OFF");
      if (recognition) {
        try {
          recognizing = false;
          recognition.stop();
        } catch (error) {
          console.error("❌ recognition.stop() 오류:", error);
        }
      }
      return;
    }

    
    if (text === "mic_on") {
      const currentPath = window.location.pathname;

      const disableVoice = localStorage.getItem("disableVoice") === "true";
        if (currentPath === "/order" && disableVoice) {
          console.log("🚫 /order에서 disableVoice=true → mic_on 무시");
          return;
        }

      console.log("🔊 서버 지시: 마이크 ON");

      if (recognizing || isStarting) {
        console.log("⏭️ 이미 마이크 켜는 중이거나 켜짐 상태 → 무시");
        return;
      }



      if (recognition && recognizing) {
        try {
          recognition.abort();
        } catch (e) {
          console.warn("⚠️ abort 중 오류:", e);
        }
        recognizing = false;
      }

      setTimeout(() => {
        startRecognition();
      }, 200);

      return;
    }

      
    if (text === "goto_menu") {
      console.log("📢 서버 지시: /order 페이지로 이동");
      localStorage.setItem("continueRecognition", "true");
      window.location.href = "/order";
      return;
    }

    if (text === "go_to_pay") {
      const clientId = localStorage.getItem("client_id");
      if (clientId) {
        console.log("📢 서버 지시: /pay_all 페이지로 이동");
        location.assign(`/pay_all?client_id=${clientId}`);
      } else {
        console.warn("❌ client_id가 없습니다. 이동 취소");
      }
      return;
    }

    if (text === "go_to_order2") {
      console.log("📢 서버 지시: /order2 페이지로 이동");
      localStorage.setItem("continueRecognition", "false");  // ❌ 음성인식 비활성화
      window.location.href = "/order2/";
      return;
    }



    if (text === "set_resume_flag") {
      console.log("🧭 resume 플래그 설정");
      localStorage.setItem("continueRecognition", "true");
      return;
    }

    console.log("🧭 현재 받은 메시지:", text);
    if (text === "go_to_done") {
      console.log("✅ done 페이지로 이동 시도");
      window.location.href = "/done";
    }



    if (text === "goto_start") {
      console.log("📢 서버 지시: /start 페이지로 이동");
      if (recognizing && recognition) {
        recognizing = false;
        recognition.stop();
        console.log("🛑 음성 인식 중단 후 페이지 이동");
      }
      window.location.href = "/start";
      return;
    }

    if (text === "set_disable_voice") {
      console.log("🚫 음성 비활성화 플래그 설정");
      localStorage.setItem("disableVoice", "true");
      return;
    }

  };

  socket.onclose = (event) => {
    console.warn("🔌 WebSocket 연결 종료됨. 재연결 시도...");
    console.log("🔌 WebSocket 종료 상세:", event.code, event.reason);

  // 🔻 아래 줄을 주석처리해서 자동 새로고침 중단!
  // setTimeout(() => {
  //   window.location.reload();  // 또는 reconnectSocket()
  // }, 100);  // ⏱ 1초 후 재시도
  };


  socket.onerror = (error) => {
    console.error("❌ W ebSocket 오류:", error);
  };
}


// 🔼 다른 함수들과 함께, startRecognition() 함수 정의 전에!
function stripSystemPrompts(text) {
  const patterns = [
    "결제를진행할까요",
    "옵션선택을진행할까요",
    "음성주문을시작합니다",
    "어떤메뉴를원하세요",
    "음성으로주문하시겠습니까",
    "아메리카노2000원입니다옵션선택을진행할까요"
  ];
  for (const pattern of patterns) {
    if (text.startsWith(pattern)) {
      text = text.replace(pattern, "");
    }
  }
  return text.trim();
}

function startRecognition() {
  console.log("📣 startRecognition() 호출됨");
  if (recognizing || isStarting) {
    console.log("⏭️ 마이크 켜는 중이거나 이미 켜짐 → 무시");
    return;

  }
  isStarting = true;  // 🔐 여기서만 설정
  recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
  recognition.lang = 'ko-KR';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.continuous = true;

  recognition.onstart = () => {
    console.log("🎙️ 마이크 켜짐 (onstart)");
  };

  recognition.onspeechstart = () => {
    console.log("🔉 사용자 발화 감지됨");
  };

  recognition.onresult = (event) => {
    const result = event.results[event.results.length - 1][0].transcript.trim();
    console.log('🎤 인식된 텍스트:', result);

    let cleanText = result.replace(/\s/g, '').toLowerCase();

    cleanText = stripSystemPrompts(cleanText);

    const phrasesToIgnore = [
      "음성으로주문하시겠습니까",
      "음성주문을시작합니다",
      "어떤메뉴를원하세요",
      "옵션선택을진행할까요",
      "아메리카노2000원입니다옵션선택을진행할까요"
    ];

    const shouldIgnore = phrasesToIgnore.some(p => cleanText.startsWith(p));

    if (shouldIgnore) {
      console.log("⏭️ 안내 문장은 전송 생략됨");
      return;
    }

    const positives = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ"];
    if (positives.includes(cleanText)) {
      console.log("✅ 긍정 응답 → 서버로 전송");
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(result);
      }
      return;
    }

    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(result);
    }
  };

  recognition.onerror = (event) => {
    console.error('❌ 음성 인식 에러:', event.error);
  };

  recognition.onend = () => {
    console.warn("🛑 음성 인식 종료됨");
    recognizing = false;
    console.log("🔇 마이크 꺼진 상태, 재시작 안함");
  };

  recognition.start();
  recognizing = true;
  isStarting = false;  // ✅ 마이크 시작 완료
  console.log("🎤 음성 인식 시작");
}

document.addEventListener("DOMContentLoaded", () => {

  // 고유 client_id 생성 및 유지
  const clientId = localStorage.getItem("client_id") || crypto.randomUUID();
  localStorage.setItem("client_id", clientId);

  // 기존 WebSocket이 있다면 닫고
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    console.warn("🔁 기존 WebSocket을 닫습니다.");
    socket.onclose = null;  // 💡 자동 재연결 방지
    socket.onmessage = null;      // ✅ 메시지 리스너 제거 (여기!)
    socket.close();
    socket = null;  // ✅ 명시적으로 null로 초기화
  }

  // 새로 연결
  createWebSocket();


  

  // ✅ 👉 /order 페이지 진입 시 음성 인식 여부 결정
  // ✅ 👉 /order 페이지 진입 시 음성 인식 여부 결정
  if (window.location.pathname === "/order") {
      const disableVoice = localStorage.getItem("disableVoice") === "true";
      if (disableVoice) {
          console.log("🔇 disableVoice=true → 플래그 제거하고 음성 인식 활성화");
          localStorage.removeItem("disableVoice");  // 플래그 제거
      }
      
      // 항상 음성 인식 시작
      console.log("🎤 음성 인식 요청");
      setTimeout(() => {
          if (socket && socket.readyState === WebSocket.OPEN) {
              socket.send("resume_from_menu");
          }
      }, 300);  // 약간 지연 후 전송
  }
  const payButton = document.querySelector(".pay-button");
  if (payButton) {
    payButton.addEventListener("click", () => {
      const clientId = localStorage.getItem("client_id");
      if (!clientId) {
        alert("client_id가 없습니다. 음성 인식이 초기화되지 않았을 수 있습니다.");
        return;
      }

      const path = window.location.pathname;
      console.log("📄 현재 경로:", path);

      if (path.startsWith("/order2/")) {
        window.location.href = `/pay_all2?client_id=${clientId}`;
      } else if (path.startsWith("/order")) {
        window.location.href = `/pay_all?client_id=${clientId}`;
      } else {
        alert("현재 페이지가 주문 페이지가 아닙니다.");
      }
    });
  }


});    


// start 페이지에서 클릭 이벤트 등록 (영구적)
document.addEventListener('DOMContentLoaded', function() {
    console.log("🎯 start 페이지 클릭 이벤트 등록 중...");
    
    // 전체 document에 클릭 이벤트 등록
    document.addEventListener('click', function(event) {
        console.log("🖱️ 클릭 감지! 현재 경로:", window.location.pathname);
        
        // start 페이지에서만 작동
        if (window.location.pathname === "/" || 
            window.location.pathname.includes("start") || 
            window.location.pathname === "/start/") {
            
            console.log("✅ start 페이지에서 클릭됨 → 음성 주문 시작");
            
            if (socket && socket.readyState === WebSocket.OPEN) {
                // start_order 메시지 전송
                socket.send("start_order");
                console.log("📤 start_order 전송됨");
                
                // TTS 요청 전송
                /*
                const ttsMessage = {
                    type: 'text_to_speech',
                    text: '음성으로 주문하시겠습니까?'
                };
                socket.send(JSON.stringify(ttsMessage));
                console.log("🎤 TTS 메시지 전송:", ttsMessage);
                */
            } else {
                console.warn("❌ WebSocket 연결 안됨:", socket?.readyState);
            }
        }
    });
    
    console.log("🎯 start 페이지 클릭 이벤트 등록 완료!");
});

