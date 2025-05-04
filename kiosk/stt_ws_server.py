import asyncio
import websockets
import os
import sys
import re
import difflib
import time
from asgiref.sync import sync_to_async

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

AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION

connected_clients = set()
client_states = {}

def is_positive(text):
    positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ", "좋습니다", "그렇죠"]
    return match_fuzzy(text, positive_words)


def is_negative(text):
    negative_words = ["아니", "싫어", "안돼", "노", "그만", "아니요", "안 할래"]
    return match_fuzzy(text, negative_words)

def match_fuzzy(text, candidates):
    for word in candidates:
        ratio = difflib.SequenceMatcher(None, text, word).ratio()
        if ratio > 0.7:
            return True
    return False

def synthesize_speech(text):
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    audio_config = AudioOutputConfig(use_default_speaker=True)
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    return result.reason == ResultReason.SynthesizingAudioCompleted

def clean_input(text):
    text = re.sub(r"[^\w가-힣]", "", text)
    text = text.replace(" ", "").lower()
    for prefix in ["음성으로주문하시겠습니까", "음성주문을시작합니다", "어떤메뉴를원하세요", "다시메뉴를말씀해주세요", "다시말씀해주세요"]:
        if text.startswith(prefix):
            text = text[len(prefix):]
    for j in ["을", "를", "이", "가", "은", "는", "에", "에서", "로", "으로", "도", "만", "께", "한테", "에게", "랑", "하고"]:
        if text.endswith(j):
            text = text[:-len(j)]
            break
    return text

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
        "first_order_done": False
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
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                await asyncio.sleep(1)  # 추가: 1초 간격으로 체크
                continue

            if state["step"] == "waiting_shot_retry":
                elapsed = time.time() - state.get("shot_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "샷 추가 여부를 다시 말씀해주세요. 네 또는 아니요로 대답해 주세요."
                    state["step"] = "ask_shot"
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                await asyncio.sleep(1)
                continue

            if state["step"] == "waiting_size_retry":
                elapsed = time.time() - state.get("size_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "사이즈를 다시 말씀해주세요. 보통 또는 큰 사이즈 중 하나를 선택해주세요."
                    state["step"] = "choose_size"
                    state["last_question"] = response_text
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                await asyncio.sleep(1)
                continue
            
            if state["step"] == "waiting_temp_retry":
                elapsed = time.time() - state.get("temp_prompt_time", 0)
                if elapsed >= 4:
                    response_text = "온도를 다시 말씀해주세요. 핫 또는 아이스로 대답해 주세요."
                    state["step"] = "choose_temp"
                    state["last_question"] = response_text
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                await asyncio.sleep(1)
                continue

            message = await websocket.recv()
            text = message.strip()
            print(f"📨 받은 메시지: {text}")

            if text == "start_order":
                response_text = "음성으로 주문하시겠습니까?"
                state.update({"step": "await_start", "cart": [], "finalized": False})
                await websocket.send(response_text)
                synthesize_speech(response_text)
                continue

            if text == "resume_from_menu":
                print("🔁 클라이언트 재연결 → 메뉴 선택 상태로 복원됨")
                state["step"] = "await_menu"
                continue

            cleaned_text = clean_input(text)
            print(f"🧹 정제된 텍스트: '{cleaned_text}'")
            print(f"🧭 현재 상태: {state['step']}")

            if "last_question" in state and state["last_question"]:
                question_cleaned = clean_input(state["last_question"])
                if question_cleaned and question_cleaned in cleaned_text:
                    cleaned_text = cleaned_text.replace(question_cleaned, "")
                    print(f"🧹 시스템 질문 제거 후 텍스트: '{cleaned_text}'")



            if not cleaned_text:
                continue

            response_text = ""

            if state["step"] == "await_start":
                if is_positive(cleaned_text):
                    response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
                    await websocket.send("goto_menu")
                    synthesize_speech(response_text)
                    state["step"] = "await_menu"
                    state["first_order_done"] = True
                    continue
                elif is_negative(cleaned_text):
                    response_text = "일반 키오스크로 주문을 진행해주세요."
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    client_states.pop(websocket)
                    return

            elif state["step"] == "await_menu":
                menu_items = await sync_to_async(list)(MenuItem.objects.all())
                menu_names_cleaned = [i.name.replace(" ", "").lower() for i in menu_items]
                close_matches = difflib.get_close_matches(cleaned_text, menu_names_cleaned, n=1, cutoff=0.5)

                matched_item = None
                if close_matches:
                    match_name = close_matches[0]
                    for item in menu_items:
                        if item.name.replace(" ", "").lower() == match_name:
                            matched_item = item
                            break

                if matched_item:
                    state.update({
                        "menu": matched_item.name,
                        "price": int(matched_item.price),
                        "category": matched_item.category,
                        "options": {}
                    })
                    if matched_item.category == "디저트":
                        state["cart"].append({"name": matched_item.name, "options": {}, "price": state["price"]})
                        response_text = f"{matched_item.name} {state['price']}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요?"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        response_text = f"{matched_item.name} {state['price']}원입니다. 옵션 선택을 진행할까요?"
                        state["step"] = "confirm_options"
                else:
                    response_text = "죄송합니다. 다시 메뉴를 말씀해주세요."

            elif state["step"] == "confirm_options":
                if is_positive(cleaned_text):
                    response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                    state["step"] = "choose_size"
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
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    continue  

            elif state["step"] == "choose_temp":
                if "아이스" in cleaned_text:
                    state["options"]["temp"] = "아이스"
                elif "핫" in cleaned_text:
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
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
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
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
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
                    state["options"]["shot"] = "없음"

                state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})

            elif state["step"] == "confirm_additional":
                if is_positive(cleaned_text):
                    response_text = "어떤 메뉴를 원하세요?"
                    state["step"] = "await_menu"
                elif is_negative(cleaned_text):
                    total = sum(item["price"] for item in state["cart"])
                    summary = "주문 내역입니다:\n"
                    for item in state["cart"]:
                        if item["options"]:
                            size = item["options"].get("size")
                            temp = item["options"].get("temp")
                            shot = item["options"].get("shot")

                            if size == "큰":
                                size = "큰거"

                            opt_text = ", ".join([
                                f"사이즈 {size}" if size else "",
                                f"{temp}" if temp else "",
                                f"{shot}" if shot else ""
                            ])
                            opt_text = ", ".join([o for o in opt_text.split(", ") if o]) or "기본 옵션"

                            summary += f"- {item['name']} ({opt_text}) {item['price']}원\n"
                        else:
                            summary += f"- {item['name']} {item['price']}원\n"
                    summary += f"총 결제 금액은 {total}원입니다. 결제를 진행합니다."
                    await websocket.send(summary)
                    synthesize_speech(summary)
                    await asyncio.sleep(5)
                    final_msg = "결제가 완료되었습니다. 감사합니다."
                    await websocket.send(final_msg)
                    synthesize_speech(final_msg)

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

                else:
                    response_text = ""
                    state["step"] = "waiting_additional_retry"
                    state["additional_prompt_time"] = time.time()
                    continue


            else:
                response_text = "죄송합니다. 다시 말씀해주세요."

            if response_text:
                state["last_question"] = response_text
                await websocket.send(response_text)
                synthesize_speech(response_text)

    except websockets.ConnectionClosed:
        print("❌ 클라이언트 연결 종료")
    finally:
        connected_clients.remove(websocket)
        client_states.pop(websocket, None)

async def main():
    async with websockets.serve(echo, "localhost", 8002):
        print("✅ WebSocket 서버가 8002번 포트에서 실행 중")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
