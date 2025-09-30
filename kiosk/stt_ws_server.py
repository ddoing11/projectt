import asyncio
import websockets
import os
import sys
import re
import difflib
import time
from asgiref.sync import sync_to_async
from difflib import SequenceMatcher
from django.db import connection
from django.db.utils import OperationalError
import json
import base64

# ✅ 상태 저장 딕셔너리들
client_sessions = {}  # client_id → state 매핑
client_states = {}    # websocket → state 매핑

async def send_text(websocket, message):
    await websocket.send(message)

# Django 설정
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.aptitude.settings")
import django
django.setup()

from django.conf import settings
from azure.cognitiveservices.speech import (
    SpeechConfig, SpeechSynthesizer, ResultReason
)
from kiosk.models import MenuItem

# 환경 설정
AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION

connected_clients = set()

# 🔒 제어 메시지(상태머신에 태우지 않을 것들)
CONTROL_MSGS = {
    "mic_on", "mic_off", "read_cart", "pay_all_ready",
    "done_page_ready", "request_mic_on"  # ← 추가
}

# --------------------------------
# DB 커넥션 보장
# --------------------------------
@sync_to_async
def ensure_mysql_connection():
    from django.db import connection
    from django.db.utils import OperationalError
    try:
        connection.cursor()
    except OperationalError:
        connection.close()

@sync_to_async
def get_price_from_db(menu_name):
    try:
        item = MenuItem.objects.get(name=menu_name)
        return float(item.price)
    except MenuItem.DoesNotExist:
        print(f"❌ 메뉴 '{menu_name}'에 대한 가격 정보를 찾을 수 없습니다.")
        return 0

# ----------------------------
# 감정/의도 판별 유틸
# ----------------------------
def match_fuzzy(text, candidates):
    for word in candidates:
        ratio = difflib.SequenceMatcher(None, text, word).ratio()
        if ratio > 0.6:
            return True
    return False

def is_positive(text):
    text = text.strip().lower()
    positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ", "좋습니다", "그렇죠",
                      "네네", "예스", "예쓰", "yes", "응응", "엉", "에", "이때"]
    if text in positive_words:
        return True
    for w in positive_words:
        if text.endswith(w):
            return True
    return match_fuzzy(text, positive_words)

def is_negative(text):
    negative_words = ["아니", "싫어", "안돼", "노", "그만", "아니요", "안할래"]
    return any(word in text for word in negative_words) or match_fuzzy(text, negative_words)

def has_order_intent(text):
    order_keywords = ["주세요", "주문", "먹고", "마시고", "갖고", "주라", "하고", "시킬게", "시키고", "줘", "할래"]
    return any(k in text for k in order_keywords)

# ----------------------------
# 옵션 반영 단가 계산 공통 함수
# ----------------------------
async def compute_unit_price(name: str, options: dict) -> int:
    base = await get_price_from_db(name)
    extra = 0
    if options:
        size = options.get("size")
        shot = options.get("shot")
        if size == "큰":
            extra += 500
        if shot == "1샷":
            extra += 300
        elif shot == "2샷":
            extra += 600
    return int(base + extra)

# ----------------------------
# 🔊 서버에서 오디오를 메모리로 받아 클라이언트로 전송
# ----------------------------
async def synthesize_speech(text, websocket=None, activate_mic=True, play_ding=False):
    from azure.cognitiveservices.speech import SpeechSynthesisOutputFormat
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = "ko-KR-SunHiNeural"
    speech_config.set_speech_synthesis_output_format(
        SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
    )
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=None)

    result = synthesizer.speak_text_async(text).get()
    if result.reason == ResultReason.SynthesizingAudioCompleted:
        b64_audio = base64.b64encode(result.audio_data).decode('utf-8')
        if websocket:
            await websocket.send(json.dumps({
                "type": "tts_audio",
                "data": b64_audio,
                "activate_mic": activate_mic,  # TTS 끝나고 mic_on이 필요한지
                "play_ding": play_ding         # TTS 끝나고 ding 재생 여부
            }))
    return result.reason == ResultReason.SynthesizingAudioCompleted

# ----------------------------
# 텍스트 정제
# ----------------------------
def clean_input(text):
    original_text = text
    original_cleaned = text.strip().lower()
    text = re.sub(r"[^\w가-힣]", "", text)
    text = text.replace(" ", "").lower()

    system_phrases = ["선택해주세요", "말씀해주세요", "대답해주세요", "해주세요"]
    for phrase in system_phrases:
        if text.endswith(phrase):
            text = text[: -len(phrase)]

    question_prefixes = [
        "음성으로주문하시겠습니까", "음성주문을시작합니다", "어떤메뉴를원하세요",
        "다시메뉴를말씀해주세요", "다시말씀해주세요",
        "같은옵션으로주문할까요", "옵션을진행할까요", "아메리카노다시주문하시겠어요", "사추가하시겠습니까",
        "같은옵션으로주문할까요네또는아니요로말씀해주세요",
        "옵션을진행할까요네또는아니요로말씀해주세요", "동일한옵션으로하나다담을까요",
        "추가주문여부를다시말씀해주세요", "메뉴있으신가요", "음성으로주문하시겠습니다",
        "차추가하시겠습니까", "사추가여부를다시", "큰사이즈는500원이추가됩니다", "결제를진행할까요"
    ]
    for _ in range(3):
        for phrase in question_prefixes:
            if text.startswith(phrase):
                text = text[len(phrase):]

    SYSTEM_SUFFIXES = [
        "네또는아니요로대답해주세요",
        "다시말씀해주세요네",
        "네또는아니요로말씀해주세요",
        "네또는아니요로답해주세요"
    ]
    for suffix in SYSTEM_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]

    if not text.strip():
        all_phrases = question_prefixes + SYSTEM_SUFFIXES
        for p in all_phrases:
            if original_cleaned.startswith(p) or original_cleaned.endswith(p):
                return ""
        return original_text

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
    if text_clean.startswith(gpt_clean[:20]):
        return text_clean.replace(gpt_clean, "").strip()
    return text

def fuzzy_remove_question(cleaned_text, last_question):
    if not last_question or len(cleaned_text) <= 2:
        return cleaned_text
    q_cleaned = clean_input(last_question)
    ratio = SequenceMatcher(None, cleaned_text, q_cleaned).ratio()
    if ratio > 0.85 and q_cleaned in cleaned_text:
        result = cleaned_text.replace(q_cleaned, "").strip()
        if result == "":
            return cleaned_text
        return result
    return cleaned_text

# ----------------------------
# GPT (설명/추천 전용)
# ----------------------------
from openai import OpenAI
client = OpenAI(api_key=settings.OPENAI_API_KEY)

async def get_chatgpt_response(user_input, gpt_messages):
    await ensure_mysql_connection()
    menu_items = await sync_to_async(list)(MenuItem.objects.all())
    menu_names_cleaned = [item.name.replace(" ", "").lower() for item in menu_items]
    user_cleaned = user_input.replace(" ", "").lower()

    category = None
    if "디저트" in user_cleaned:
        category = "디저트"
    elif "음료" in user_cleaned:
        category = "음료"
    elif "커피" in user_cleaned:
        category = "커피"
    elif "차" in user_cleaned:
        category = "차"

    if category:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.filter(category=category))
    else:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.all())

    menu_names = [item.name for item in menu_items]
    menu_list_text = ", ".join(menu_names)

    matched_menu = None
    for original, cleaned in zip(menu_items, menu_names_cleaned):
        if cleaned in user_cleaned or cleaned == user_cleaned:
            matched_menu = original.name
            break

    base_prompt = (
        f"절대 '나는 주문을 받을 수 없어'라는 말은 하지 마. "
        f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
        f"메뉴 리스트: {menu_list_text} "
        "이외의 메뉴는 절대 언급하지 마세요. 손님이 메뉴 설명을 요청하면 해당 메뉴를 1문장으로 짧게 설명하고, "
        "추천을 요청하면 2개의 메뉴를 소개하고 각 한 문장씩 소개하세요. 주문은 받지 마세요. "
        "맥락없는 소리(ex: '음', '요')는 무시하세요. "
        "없는 메뉴를 요청하면 리스트 안에서 비슷한 걸 친절히 추천하세요. "
        "손님이 영어로 말하면 영어로 답하세요."
    )

    if matched_menu:
        system_prompt = (
            f"{matched_menu}의 맛을 1문장으로만 간결하게 설명하세요. "
            f"추천은 하지 마세요. 예: '달고나라떼는 달콤하고 부드러운 맛의 음료입니다.'"
        )
    else:
        system_prompt = base_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]
    response = client.chat.completions.create(
        model="gpt-4-turbo",
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )
    reply = response.choices[0].message.content.strip()
    gpt_messages.append({"role": "user", "content": user_input})
    gpt_messages.append({"role": "assistant", "content": reply})
    return reply

# ----------------------------
# 메인 핸들러
# ----------------------------
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
        "gpt_messages": [],
        "last_question": "",
        "last_heard": "",
        "disable_voice": False,
        "path": ""
    }
    state = client_states[websocket]

    try:
        while True:
            # ---- 재질문 타임아웃 처리 ----
            if state.get("finalized"):
                await asyncio.sleep(0.2)
                continue

            if state["step"] == "waiting_additional_retry":
                cleaned = state.get("last_heard", "").strip().lower()
                if is_positive(cleaned):
                    await websocket.send("mic_off")
                    response_text = "어떤 메뉴를 원하세요?"
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    state["step"] = "await_menu"
                    continue
                elif is_negative(cleaned):
                    if state.get("path") == "/start":
                        await websocket.send("set_resume_flag")

                    await send_text(websocket, "go_to_pay")
                    state["step"] = "confirm_payment"

                    # 장바구니 요약
                    from collections import defaultdict
                    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})
                    for it in state["cart"]:
                        size = it["options"].get("size")
                        temp = it["options"].get("temp")
                        shot = it["options"].get("shot")
                        opt_parts = []
                        if size:
                            opt_parts.append("사이즈 큰 거" if size == "큰" else f"사이즈 {size}")
                        if temp:
                            opt_parts.append(temp)
                        if shot:
                            opt_parts.append("샷 없음" if shot == "없음" else shot)
                        opt_text = ", ".join(opt_parts)
                        key = f"{it['name']}|{opt_text}"
                        counter[key]["count"] += it.get("count", 1)
                        counter[key]["total_price"] += it.get("price", 0) * it.get("count", 1)
                        counter[key]["name"] = it["name"]
                        counter[key]["options"] = opt_text

                    summary = "주문 내역입니다:\n"
                    total = 0
                    for v in counter.values():
                        summary += f"- {v['name']} {v['options']}  {v['count']}개에 {v['total_price']:,}원\n"
                        total += v["total_price"]

                    final_prompt = f"{summary.strip()}\n총 결제 금액은 {total:,}원입니다."
                    await websocket.send(json.dumps({"type": "cart_summary", "text": final_prompt}))
                    state["step"] = "confirm_payment"
                    state["last_question"] = final_prompt
                    state["cart_summary"] = final_prompt

                    await websocket.send("go_to_pay")
                    await websocket.send("mic_off")
                    await synthesize_speech(final_prompt, websocket, activate_mic=True, play_ding=True)
                    continue

                elapsed = time.time() - state.get("additional_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "추가 주문 여부를 다시 말씀해주세요."
                    state["step"] = "confirm_additional"
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                await asyncio.sleep(0.2)
                continue

            if state["step"] == "waiting_shot_retry":
                elapsed = time.time() - state.get("shot_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "샷 추가 여부를 다시 말씀해주세요. 네 또는 아니요로 대답해 주세요."
                    state["step"] = "ask_shot"
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                await asyncio.sleep(0.2)
                continue

            if state["step"] == "waiting_size_retry":
                elapsed = time.time() - state.get("size_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "사이즈를 다시 말씀해주세요. 보통 또는 큰 사이즈 중 하나를 선택해주세요."
                    state["step"] = "choose_size"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                await asyncio.sleep(0.2)
                continue

            if state["step"] == "waiting_temp_retry":
                elapsed = time.time() - state.get("temp_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "온도를 다시 말씀해주세요. 따듯한 것 또는 차가운 것으로 대답해 주세요."
                    state["step"] = "choose_temp"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                await asyncio.sleep(0.2)
                continue

            # ---- 메시지 수신 ----
            message = await websocket.recv()
            text = message.strip()
            print(f"📨 받은 메시지: {text}")
            print(f"🔁 요청 시점 websocket id: {id(websocket)}")

            # ---- 제어 메시지: 상태머신에서 분리 ----
            if text in CONTROL_MSGS:
                if text == "done_page_ready":
                    await synthesize_speech("결제가 완료되었습니다. 감사합니다.", websocket, activate_mic=False)

                elif text == "read_cart":
                    # 한 번만 묶어서 전송
                    items = []
                    total = 0
                    for it in state.get("cart", []):
                        name = it.get("name")
                        options = it.get("options", {})
                        count = it.get("count", 1)
                        unit_price = await compute_unit_price(name, options)
                        it["price"] = unit_price
                        it["total_price"] = unit_price * count
                        items.append({"name": name, "count": count, "price": unit_price})
                        total += it["total_price"]
                    await websocket.send(json.dumps({"type": "cart_items", "items": items}, default=str))
                    print("📤 cart_items 전송 완료:", items)

                elif text == "request_mic_on":
                    # ✅ 여기서 바로 클라이언트에 mic_on 신호 내려주기
                    await websocket.send("mic_on")
                    print("📤 mic_on 전송 완료")

                continue

            # ---- page_info (상태 복원/초기화) ----
            try:
                data = json.loads(message)
                if data.get("type") == "page_info":
                    client_id = data.get("client_id")
                    path = data.get("path")
                    state["client_id"] = client_id
                    state["path"] = path
                    print(f"📄 클라이언트 페이지 경로: {path}, client_id: {client_id}")

                    if client_id in client_sessions:
                        print("🔁 기존 상태 복원")
                        # 이미 저장해둔 세션 state로 교체
                        restored = client_sessions[client_id]
                        client_states[websocket] = restored
                        state = restored
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
                            "last_question": "",
                            "last_heard": "",
                            "disable_voice": False,
                            "path": path
                        }
                        client_sessions[client_id] = state
                        client_states[websocket] = state

                    # ✅ 여기서 불필요하게 mic_on을 보내지 않음.
                    #   마이크는 TTS의 activate_mic=True 로만 켜도록 일원화.
                    continue

            except json.JSONDecodeError:
                pass  # 일반 텍스트는 아래에서 처리

            # ---- 일반 텍스트 처리 ----
            state = client_states.get(websocket)
            if not state:
                continue

            cleaned_text = clean_input(text)
            if not cleaned_text.strip():
                cleaned_text = text.strip()
            cleaned_text = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))
            last_gpt_reply = state["gpt_messages"][-1]["content"] if state["gpt_messages"] else ""
            cleaned_text = strip_gpt_response_prefix(cleaned_text, last_gpt_reply)
            state["last_heard"] = cleaned_text

            # ---- 재진입 헬퍼 ----
            if text == "resume_from_menu":
                print("🔁 클라이언트 재연결 → 메뉴 선택 상태로 복원됨")
                state["step"] = "await_menu"
                response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
                await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                continue

            elif text == "request_summary_tts":
                prompt = state.get("cart_summary")
                if prompt:
                    await websocket.send("mic_off")
                    await synthesize_speech(prompt, websocket, activate_mic=True, play_ding=True)
                continue

            elif text == "resume_from_pay":
                print("🔁 pay_all 복귀 요청 수신 → 장바구니 요약 및 결제 질문 재출력")
                state["step"] = "confirm_payment"
                summary = state.get("cart_summary", "")
                if summary:
                    await synthesize_speech(summary.strip(), websocket, activate_mic=False)
                followup = state.get("last_question", "총 결제 금액은 ~원입니다.")
                await synthesize_speech(followup.strip(), websocket, activate_mic=True, play_ding=True)
                continue

            # ---- START 시퀀스 (패치 A: 일원화) ----
            if text == "start_order":
                state.update({
                    "step": "await_start",
                    "cart": [],
                    "finalized": False,
                    "first_order_done": False,
                    "menu": None,
                    "options": {},
                    "price": 0,
                    "category": None,
                    "count": 1
                })
                # TTS 한 번만. 끝나면 클라이언트가 (띵) + mic_on
                await websocket.send("mic_off")
                await synthesize_speech(
                    "음성으로 주문하시겠습니까?",
                    websocket,
                    activate_mic=True,     # 끝나면 마이크 켤 준비
                    play_ding=True         # 끝나면 (띵) 재생
                )
                continue

            response_text = ""

            # ---- await_start 단계: 네/아니요 ----
            if state["step"] == "await_start":
                if is_positive(cleaned_text):
                    # 안내 멘트는 클라에서 처리 → 바로 메뉴 페이지
                    await websocket.send("goto_menu")
                    state["step"] = "await_menu"
                    await asyncio.sleep(0.2)
                    continue
                elif is_negative(cleaned_text):
                    await synthesize_speech("일반 키오스크로 진행하세요.", websocket, activate_mic=False)
                    await asyncio.sleep(0.5)
                    await websocket.send("set_disable_voice")
                    await asyncio.sleep(0.05)
                    await websocket.send("go_to_order2")
                    client_states.pop(websocket, None)
                    continue
                else:
                    short_ignore = ["오", "우", "이", "흠", "요"]
                    if cleaned_text in short_ignore or not cleaned_text.strip():
                        continue

            # ---- 메뉴 단계 ----
            if state["step"] == "await_menu":
                await ensure_mysql_connection()
                menu_items = await sync_to_async(list)(MenuItem.objects.all())
                cleaned_user_text = cleaned_text.replace(" ", "").lower()
                matched_item = next(
                    (item for item in menu_items if item.name.replace(" ", "").lower() in cleaned_user_text),
                    None
                )

                def is_order_expression(txt):
                    order_phrases = [
                        "주세요", "주문할게요", "시킬게요", "갖고갈게요",
                        "먹을게요", "살게요", "할게요", "줘", "주라", "줄래",
                        "도하나주세요", "하나주세요", "더주세요"
                    ]
                    t = txt.replace(" ", "").lower()
                    for phrase in order_phrases:
                        if phrase in t:
                            return True
                        if difflib.SequenceMatcher(None, t, phrase).ratio() > 0.7:
                            return True
                    return False

                def is_repeat_order(txt):
                    repeat_keywords = [
                        "같은걸로", "같은거", "그걸로", "그거", "방금", "또하나", "하나더", "다시",
                        "같은거하나더", "같은메뉴", "아까", "한번더", "이전주문", "전에주문한거", "이전과같은"
                    ]
                    t = txt.replace(" ", "").lower()
                    return any(k in t for k in repeat_keywords)

                # 반복 주문
                if is_repeat_order(cleaned_user_text):
                    if state["cart"]:
                        last_item = state["cart"][-1]
                        try:
                            item_obj = await sync_to_async(MenuItem.objects.get)(name=last_item["name"])
                            category = item_obj.category
                        except MenuItem.DoesNotExist:
                            category = "기타"
                        state["last_repeat_item"] = {**last_item, "category": category}
                        response_text = f"{last_item['name']} 다시 주문하시겠어요? 이전과 동일한 옵션으로 하나 더 담을까요?"
                        state["step"] = "confirm_repeat_options"
                    else:
                        response_text = "이전에 주문한 메뉴가 없어요. 다시 메뉴를 말씀해주세요."
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue

                has_clear_order = is_order_expression(cleaned_user_text)
                is_exact_menu = matched_item and matched_item.name.replace(" ", "").lower() == cleaned_user_text
                print("🧪 유사도 기반 매칭:", matched_item.name if matched_item else None)
                print("📌 주문 표현:", has_clear_order, "| 정확 메뉴:", is_exact_menu)

                if matched_item and (has_clear_order or is_exact_menu):
                    item = matched_item
                    state.update({
                        "menu": item.name,
                        "price": int(item.price),   # 기본 단가(옵션 전)
                        "category": item.category,
                        "options": {},
                        "count": 1
                    })
                    if item.category == "디저트":
                        unit_price = await compute_unit_price(item.name, {})
                        state["cart"].append({
                            "name": item.name,
                            "options": {},
                            "price": unit_price,
                            "total_price": unit_price,
                            "count": 1
                        })
                        response_text = f"{item.name} {unit_price}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요? 네 또는 아니요로 대답해주세요"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                        await websocket.send("mic_off")
                        await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    else:
                        response_text = f"{item.name} {state['price']}원입니다. 옵션 선택을 진행할까요?"
                        state["step"] = "confirm_options"
                        await websocket.send("mic_off")
                        await websocket.send(response_text)
                        await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                else:
                    # ✅ 너무 짧은 입력은 설명 TTS 생략 (잡음/중간 입력 방지)
                    if len(cleaned_user_text) >= 2:
                        gpt_reply = await get_chatgpt_response(text, state["gpt_messages"])
                        await websocket.send("mic_off")
                        await websocket.send(gpt_reply)
                        await synthesize_speech(gpt_reply, websocket, activate_mic=True, play_ding=True)
                continue

            # ---- 반복 주문 옵션 확인 ----
            if state["step"] == "confirm_repeat_options":
                if cleaned_text.strip() in ["같은옵션으로주문할까요"]:
                    continue
                if is_positive(cleaned_text.strip()):
                    item = state.get("last_repeat_item")
                    if item:
                        if item.get("category") == "디저트":
                            unit_price = await compute_unit_price(item["name"], {})
                            state["cart"].append({
                                "name": item["name"],
                                "options": {},
                                "price": unit_price,
                                "total_price": unit_price,
                                "count": 1
                            })
                            response_text = f"{item['name']}을 담았습니다. 추가로 주문하시겠습니까?"
                        else:
                            unit_price = await compute_unit_price(item["name"], item.get("options", {}))
                            state["cart"].append({
                                "name": item["name"],
                                "options": item.get("options", {}).copy(),
                                "price": unit_price,
                                "total_price": unit_price,
                                "count": 1
                            })
                            response_text = f"{item['name']}을(를) 동일한 옵션으로 하나 더 담았습니다. 추가로 주문하시겠습니까?"
                        await websocket.send("mic_off")
                        await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    continue
                elif is_negative(cleaned_text.strip()):
                    repeat_item = state.get("last_repeat_item")
                    if repeat_item:
                        state["menu"] = repeat_item["name"]
                        try:
                            item_obj = await sync_to_async(MenuItem.objects.get)(name=repeat_item["name"])
                            state["price"] = int(item_obj.price)
                            state["category"] = item_obj.category
                        except MenuItem.DoesNotExist:
                            state["price"] = repeat_item.get("price", 0)

                    if state.get("category") == "디저트":
                        unit_price = await compute_unit_price(state["menu"], {})
                        state["cart"].append({
                            "name": state["menu"],
                            "options": {},
                            "price": unit_price,
                            "total_price": unit_price,
                            "count": 1
                        })
                        response_text = f"{state['menu']}을 담았습니다. 추가로 주문하시겠습니까?"
                        await websocket.send("mic_off")
                        await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        if state["category"] in ["커피", "음료", "차"]:
                            response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                            state["step"] = "choose_size"
                        else:
                            response_text = "다시 옵션을 선택해주세요."
                            state["step"] = "confirm_options"
                        await websocket.send("mic_off")
                        await websocket.send(response_text)
                        await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue
                else:
                    response_text = "같은 옵션으로 주문할까요? 네 또는 아니요로 말씀해주세요."
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue

            # ---- 옵션 진행 여부 ----
            if state["step"] == "confirm_options":
                if is_positive(cleaned_text):
                    response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                    state["step"] = "choose_size"
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue
                elif is_negative(cleaned_text):
                    category = state["category"]
                    if category in ["커피", "음료"]:
                        state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
                    elif category == "차":
                        state["options"] = {"size": "보통", "temp": "아이스"}
                    else:
                        state["options"] = {}
                    unit_price = await compute_unit_price(state["menu"], state["options"])
                    state["cart"].append({
                        "name": state["menu"],
                        "options": state["options"].copy(),
                        "price": unit_price,
                        "total_price": unit_price,
                        "count": 1
                    })
                    response_text = f"기본 옵션으로 {state['menu']}를 장바구니에 담았습니다. 추가로 주문하시겠습니까? 네 또는 아니요로 대답해주세요"
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    continue
                else:
                    response_text = "옵션을 진행할까요? 네 또는 아니요로 말씀해주세요."
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue

            # ---- 사이즈 선택 ----
            if state["step"] == "choose_size":
                if "큰" in cleaned_text:
                    state["options"]["size"] = "큰"
                elif "보통" in cleaned_text or "기본" in cleaned_text:
                    state["options"]["size"] = "보통"
                else:
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
                await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                continue

            # ---- 온도 선택 ----
            if state["step"] == "choose_temp":
                if any(t in cleaned_text for t in ["아이스", "차가운", "찬거", "찬거", "시원한", "시원"]):
                    state["options"]["temp"] = "아이스"
                elif any(t in cleaned_text for t in ["핫", "하트", "하", "하스", "합", "뜨거운", "따뜻한", "드거운", "다듯한"]):
                    state["options"]["temp"] = "핫"
                else:
                    state["step"] = "waiting_temp_retry"
                    state["temp_prompt_time"] = time.time()
                    continue

                if state["category"] == "차":
                    unit_price = await compute_unit_price(state["menu"], state["options"])
                    state["cart"].append({
                        "name": state["menu"],
                        "options": state["options"].copy(),
                        "price": unit_price,
                        "total_price": unit_price,
                        "count": 1
                    })
                    response_text = f"추가 메뉴 있으신가요?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                else:
                    response_text = "샷 추가하시겠습니까?"
                    state["step"] = "ask_shot"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                continue

            # ---- 샷 여부 ----
            if state["step"] == "ask_shot":
                if "아니" in cleaned_text:
                    state["options"]["shot"] = "없음"
                    unit_price = await compute_unit_price(state["menu"], state["options"])
                    state["cart"].append({
                        "name": state["menu"],
                        "options": state["options"].copy(),
                        "price": unit_price,
                        "total_price": unit_price,
                        "count": 1
                    })
                    response_text = f"추가 메뉴 있으신가요?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue
                elif is_positive(cleaned_text):
                    response_text = "1번 추가는 +300원이고 2번 추가는 +600원입니다."
                    state["step"] = "choose_shot"
                    state["last_question"] = response_text
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    continue
                else:
                    state["step"] = "waiting_shot_retry"
                    state["shot_prompt_time"] = time.time()
                    continue

            # ---- 샷 개수 선택 ----
            if state["step"] == "choose_shot":
                if any(x in cleaned_text for x in ["2", "두"]):
                    state["options"]["shot"] = "2샷"
                elif any(x in cleaned_text for x in ["1", "한"]):
                    state["options"]["shot"] = "1샷"
                else:
                    state["step"] = "waiting_shot_retry"
                    state["shot_prompt_time"] = time.time()
                    continue

                unit_price = await compute_unit_price(state["menu"], state["options"])
                state["cart"].append({
                    "name": state["menu"],
                    "options": state["options"].copy(),
                    "price": unit_price,
                    "total_price": unit_price,
                    "count": 1
                })
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                await websocket.send("mic_off")
                await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                continue

            # ---- 추가 주문 여부 ----
            if state["step"] in ["confirm_additional", "waiting_confirm_additional"]:
                cleaned = cleaned_text.strip().lower()
                if is_positive(cleaned_text):
                    await websocket.send("mic_off")
                    response_text = "어떤 메뉴를 원하세요?"
                    await synthesize_speech(response_text, websocket, activate_mic=True, play_ding=True)
                    state["step"] = "await_menu"
                    continue
                elif is_negative(cleaned_text):
                    if state.get("path") == "/start":
                        await websocket.send("set_resume_flag")
                    await send_text(websocket, "go_to_pay")
                    state["step"] = "confirm_payment"

                    from collections import defaultdict
                    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})
                    for it in state["cart"]:
                        size = it["options"].get("size")
                        temp = it["options"].get("temp")
                        shot = it["options"].get("shot")
                        opt_parts = []
                        if size:
                            opt_parts.append("사이즈 큰 거" if size == "큰" else f"사이즈 {size}")
                        if temp:
                            opt_parts.append(temp)
                        if shot:
                            opt_parts.append("샷 없음" if shot == "없음" else shot)
                        opt_text = ", ".join(opt_parts)
                        key = f"{it['name']}|{opt_text}"
                        counter[key]["count"] += it.get("count", 1)
                        counter[key]["total_price"] += it.get("price", 0) * it.get("count", 1)
                        counter[key]["name"] = it["name"]
                        counter[key]["options"] = opt_text

                    summary = "주문 내역입니다:\n"
                    total = 0
                    for v in counter.values():
                        summary += f"- {v['name']} {v['options']}  {v['count']}개에 {v['total_price']:,}원\n"
                        total += v["total_price"]
                    final_prompt = f"{summary.strip()}\n총 결제 금액은 {total:,}원입니다."
                    state["step"] = "confirm_payment"
                    state["last_question"] = final_prompt
                    state["cart_summary"] = final_prompt
                    await websocket.send(json.dumps({"type": "cart_summary", "text": final_prompt}))
                    await websocket.send("go_to_pay")
                    await websocket.send("mic_off")
                    await synthesize_speech(final_prompt, websocket, activate_mic=True, play_ding=True)
                    continue
                else:
                    state["step"] = "waiting_confirm_additional"
                    state["last_question"] = "추가 주문 여부를 네 또는 아니요로 말씀해주세요."
                    async def delayed_reprompt():
                        await asyncio.sleep(8)
                        if state["step"] == "waiting_confirm_additional":
                            await websocket.send("mic_off")
                            await synthesize_speech(state["last_question"], websocket, activate_mic=True, play_ding=True)
                    asyncio.create_task(delayed_reprompt())
                    continue

            # ---- 결제 확인 ----
            if state["step"] in ["confirm_payment", "waiting_payment_retry"]:
                if cleaned_text in ["pay_all_ready", "read_cart", "request_mic_on"]:
                    continue
                cleaned = fuzzy_remove_question(cleaned_text, state.get("last_question", "")).strip().lower()
                if is_positive(cleaned):
                    state["step"] = "payment_in_progress"
                    try:
                        await websocket.send("popup_payment")
                    except Exception as e:
                        print(f"❌ popup_payment 전송 실패: {e}")
                    final_announce = "결제를 진행합니다."
                    await websocket.send(final_announce)
                    await synthesize_speech(final_announce, websocket, activate_mic=False)
                    await asyncio.sleep(5)
                    await websocket.send("go_to_done")
                    await asyncio.sleep(0.5)
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
                    await websocket.send("goto_start")
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
                    retry_text = "결제를 진행할까요? 네 또는 아니요로 말씀해주세요."
                    state["step"] = "waiting_payment_retry"
                    state["last_question"] = retry_text
                    await websocket.send("mic_off")
                    # ✅ activate_mic=True + play_ding=True 로 요청-응답 프로토콜 유지
                    await synthesize_speech(retry_text, websocket, activate_mic=True, play_ding=True)

                    # (지연 재프롬프트) — 동일하게 유지
                    async def delayed_payment_retry():
                        await asyncio.sleep(8)
                        if state["step"] == "waiting_payment_retry":
                            if state.get("last_question") != retry_text:
                                return
                            await websocket.send("mic_off")
                            await synthesize_speech(retry_text, websocket, activate_mic=True, play_ding=True)
                    asyncio.create_task(delayed_payment_retry())
                    continue

    except websockets.ConnectionClosed:
        print("❌ 클라이언트 연결 종료")
    finally:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        if websocket in client_states:
            client_states.pop(websocket, None)

# ----------------------------
# 서버 시작
# ----------------------------
async def main():
    port = int(os.environ.get("PORT", 8002))
    async with websockets.serve(echo, "0.0.0.0", port):
        print(f"✅ WebSocket 서버가 {port}번 포트에서 실행 중")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
