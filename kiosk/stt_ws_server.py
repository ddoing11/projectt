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

sound_path = "C:/SoundAssets/ding.wav"




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

openai.api_key = settings.OPENAI_API_KEY

AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION

connected_clients = set()
client_states = {}

def is_positive(text):
    text = text.strip().lower()
    positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ", "좋습니다", "그렇죠", "네네"]

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
    



async def synthesize_speech(text, websocket=None, activate_mic=True):
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    audio_config = AudioOutputConfig(use_default_speaker=True)
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)



    result = synthesizer.speak_text_async(text).get()

    if result.reason == ResultReason.SynthesizingAudioCompleted:
        playsound(sound_path)  # ✅ 띵 소리

        if activate_mic and websocket:
            # 📏 문장 길이 기반 마이크 ON 대기 시간 계산
            length = len(text)
            base_delay = 0.001   # 띵 소리 이후 기본 대기
            speak_time = length  * 0.01  # 글자당 0.02초

            delay = base_delay + speak_time
            print(f"⏱️ 마이크 ON까지 대기: {delay:.2f}초 (문장 길이: {length}자)")
            await asyncio.sleep(delay)
            await websocket.send("mic_on")

    return result.reason == ResultReason.SynthesizingAudioCompleted





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
        "같은옵션으로주문할까요", "옵션을진행할까요", "아메리카노다시주문하시겠어요",
        "같은옵션으로주문할까요네또는아니요로말씀해주세요",  # 완전한 문장도 포함
        "옵션을진행할까요네또는아니요로말씀해주세요", "4 추가하시겠습니다 ", "동일한 옵션으로 하나 더 담을까요", "추가 주문 여부를 다시 말씀해 주세요", "메뉴 있으신가요", "음성으로주문하시겠습니다", "차 추가하시겠습니까", "사추가여부를다시", "사추가 여부를 다시 말씀해 주세요", "사 추가하시겠습니다", "큰 사이즈는 500원이 추가됩니다", "2,500원입니다", "어떤 메뉴를 원하세요", "간단한 식사 대용으로도 좋습니다", "큰 사이즈는 500원이 추가됩니다"
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


    for j in ["을", "를", "이", "가", "은", "는", "에", "에서", "로", "으로", "도", "만", "께", "한테", "에게", "랑", "하고"]:
        if text.endswith(j):
            text = text[:-len(j)]
            break
    return text

def fuzzy_remove_question(cleaned_text, last_question):
    if not last_question or len(cleaned_text) <= 2:
        return cleaned_text  # ➤ 응답이 짧으면 제거하지 않음
    q_cleaned = clean_input(last_question)

    ratio = SequenceMatcher(None, cleaned_text, q_cleaned).ratio()
    if ratio > 0.85:
        print(f"🧽 시스템 질문과 유사도 {ratio:.2f} → 질문 제거됨")
        return cleaned_text.replace(q_cleaned, "")
    return cleaned_text

def strip_gpt_response_prefix(text, last_gpt_reply):
    if not last_gpt_reply:
        return text
    gpt_clean = clean_input(last_gpt_reply)
    text_clean = clean_input(text)

    if text_clean.startswith(gpt_clean[:20]):  # 앞 20자 유사성 검사
        print("🔍 GPT 응답 앞부분 포함 → 제거 시도")
        return text_clean.replace(gpt_clean, "").strip()
    return text


from openai import OpenAI

client = OpenAI(api_key=settings.OPENAI_API_KEY)

async def get_chatgpt_response(user_input, gpt_messages):
    from kiosk.models import MenuItem

    # 메뉴 불러오기
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
        menu_items = await sync_to_async(list)(MenuItem.objects.filter(category=category))
    else:
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


    if not matched_menu and not is_recommend_request:
        # ✅ 추천 요청이 아니고, 메뉴도 없음 → 차단
        reply = "죄송합니다. 저희 카페의 메뉴에는 없는 메뉴예요."
        gpt_messages.append({"role": "user", "content": user_input})
        gpt_messages.append({"role": "assistant", "content": reply})
        return reply

    # 시스템 프롬프트 생성
    base_prompt = (
        f"절대 '나는 주문을 받을 수 없어'라는 말은 하지 마. "
        f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
        f"메뉴 리스트: {menu_list_text} "
        "이외의 메뉴는 절대 언급하지 마세요. 손님이 메뉴 설명을 요청하면 해당 메뉴를 1문장으로 짧게 설명하고, "
        "추천을 요청하면 2개의 메뉴를 소개하고 각 한 문장씩 소개하세요. 주문은 받지 마세요."
        "맥락없는 소리 (ex: '음', '요' 등)은 무시하고 응답하지 마세요"
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
                elapsed = time.time() - state.get("additional_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "추가 주문 여부를 다시 말씀해주세요."
                    state["step"] = "confirm_additional"
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                await asyncio.sleep(1)  # 추가: 1초 간격으로 체크
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
                    response_text = "온도를 다시 말씀해주세요. 핫 또는 아이스로 대답해 주세요."
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

            if text == "start_order":
                response_text = "음성으로 주문하시겠습니까?"
                state.update({
                    "step": "await_start",
                    "cart": [],
                    "finalized": False,
                    "first_order_done": False,  # 필요 시 초기화
                    "menu": None,
                    "options": {},
                    "price": 0,
                    "category": None
                })
                await websocket.send(response_text)
                await synthesize_speech(response_text, websocket)

                continue


            
            if state["step"] == "await_start":
                cleaned_text = clean_input(text)
                cleaned_text = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))
                last_gpt_reply = state["gpt_messages"][-1]["content"] if state["gpt_messages"] else ""
                cleaned_text = strip_gpt_response_prefix(cleaned_text, last_gpt_reply)

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

         
                # 🔒 의미 없는 단독 음절 소음 무시 (단, 긍정/부정 응답 또는 특정 단계는 예외)
                if len(cleaned_text.strip()) <= 1 and not is_positive(cleaned_text) and not is_negative(cleaned_text):
                    # 단, choose_temp 상태일 때는 '핫' 같은 응답 허용
                    if state["step"] != "choose_temp":
                        print(f"⚠️ 너무 짧은 소리 무시: '{cleaned_text}'")
                        continue
                    else:
                        print(f"✅ choose_temp 단계에서 짧은 응답 허용: '{cleaned_text}'")


            

                
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
                    await websocket.send("goto_menu")  # 🚀 먼저 페이지 이동
                    await asyncio.sleep(0.5)  # 💡 클라이언트 로딩 대기 (필요시 늘릴 수 있음)

                    # 이후 서버가 다시 응답하도록 상태 설정만
                    state["step"] = "announce_menu_prompt"
                    continue



                elif is_negative(cleaned_text):
                    response_text = "일반 키오스크로 주문을 진행해주세요."
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket, activate_mic=False)


                    client_states.pop(websocket)
                    return

            elif state["step"] == "await_menu":
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
                        "options": {}
                    })
                    if item.category == "디저트":
                        state["cart"].append({"name": item.name, "options": {}, "price": state["price"]})
                        response_text = f"{item.name} {state['price']}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요?"
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
                                "price": item["price"]
                            })
                            response_text = f"{item['name']}을 담았습니다. 추가로 주문하시겠습니까?"

                        else:
                            # ✅ 그 외는 기존 옵션 복사
                            state["cart"].append({
                                "name": item["name"],
                                "options": item["options"].copy(),
                                "price": item["price"]
                            })
                            response_text = f"{item['name']}을(를) 동일한 옵션으로 하나 더 담았습니다. 추가로 주문하시겠습니까?"

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
                            "price": state["price"]
                        })
                        response_text = f"{state['menu']}을 담았습니다. 추가로 주문하시겠습니까?"
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
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                    response_text = f"기본 옵션으로 {state['menu']}를 장바구니에 담았습니다. 추가로 주문하시겠습니까?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
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
                    response_text = "핫 또는 아이스를 선택해주세요."
                    state["step"] = "choose_temp"
                    state["last_question"] = response_text 
                    await websocket.send("mic_off")
                    await websocket.send(response_text)
                    await synthesize_speech(response_text, websocket)

                    continue  

            elif state["step"] == "choose_temp":
                if "아이스" in cleaned_text:
                    state["options"]["temp"] = "아이스"
                elif any(t in cleaned_text for t in ["핫", "하트", "하", "하스", "합"]):
                    state["options"]["temp"] = "핫"
                else:
                    # 유효하지 않은 응답 → 재질문 대기 상태로 전환
                    state["step"] = "waiting_temp_retry"
                    state["temp_prompt_time"] = time.time()
                    continue

                if state["category"] == "차":
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
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
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
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

                state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})

            elif state["step"] == "confirm_additional":

                cleaned_for_intent = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))

                if is_positive(cleaned_text):
                    response_text = "어떤 메뉴를 원하세요?"
                    state["step"] = "await_menu"


                elif is_negative(cleaned_text):
                    total = sum(item["price"] for item in state["cart"])
                    summary = "주문 내역입니다:\n"
                    summary = "주문 내역입니다:\n"
                    from collections import defaultdict

                    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})

                    for item in state["cart"]:
                        size = item["options"].get("size")
                        temp = item["options"].get("temp")
                        shot = item["options"].get("shot")

                        # 사이즈 '큰'은 '큰 거'로 자연스럽게 표기
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

                    total = 0
                    for item in counter.values():
                        summary += f"- {item['name']} {item['options']}  {item['count']}개에 {item['total_price']}원\n"
                        total += item["total_price"]

                    summary += f"총 결제 금액은 {total}원입니다. 결제를 진행합니다."


                    await websocket.send(summary)
                    await synthesize_speech(summary, websocket, activate_mic=False)  # 마이크 off
                    await asyncio.sleep(5)
                    final_msg = "결제가 완료되었습니다. 감사합니다."
                    await websocket.send(final_msg)
                    await synthesize_speech(final_msg, websocket, activate_mic=False)  # 마이크 off

                    await asyncio.sleep(2)
                    await websocket.send("goto_start")

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

                else:
                    response_text = "추가 주문 여부를 네 또는 아니요로 말씀해주세요."
                    state["step"] = "waiting_additional_retry"
                    state["additional_prompt_time"] = time.time()

                # ✅ 여기서 공통 응답 처리
                state["last_question"] = response_text
                await websocket.send("mic_off")
                await websocket.send(response_text)
                await synthesize_speech(response_text, websocket)

                continue


            

            if response_text and state["step"] not in ["confirm_options"]:
                state["last_question"] = response_text
                await websocket.send(response_text)
                await synthesize_speech(response_text, websocket)



    except websockets.ConnectionClosed:
        print("❌ 클라이언트 연결 종료")
    finally:
        connected_clients.remove(websocket)
        client_states.pop(websocket, None)

async def main():
    port = int(os.environ.get("PORT", 8002))  # Railway에서 제공한 PORT를 사용
    async with websockets.serve(echo, "0.0.0.0", port):  # ← 반드시 "0.0.0.0"
        print(f"✅ WebSocket 서버가 {port}번 포트에서 실행 중")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())

