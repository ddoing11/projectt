import asyncio
import websockets
import os
import sys
from asgiref.sync import sync_to_async

# Django 
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

fixed_prompts = [
    "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다.",
    "핫 또는 아이스를 선택해주세요.",
    "샷 추가하시겠습니까?",
    "1번 추가는 +300원이고 2번 추가는 +600원입니다.",
    "옵션을 진행할까요? 네 또는 아니요로 말씀해주세요.",
    "보통 또는 큰 사이즈 중 하나를 말씀해주세요.",
    "핫 또는 아이스 중 하나를 선택해주세요.",
    "샷 추가 여부를 네 또는 아니요로 말씀해주세요.",
]

def is_positive(text):
    return any(word in text for word in ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ"])

def synthesize_speech(text):
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    audio_config = AudioOutputConfig(use_default_speaker=True)
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    return result.reason == ResultReason.SynthesizingAudioCompleted

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
        "finalized": False
    }
    state = client_states[websocket]

    try:
        while True:
            if state.get("finalized"):
                await asyncio.sleep(1)
                continue

            message = await websocket.recv()
            text = message.strip()
            print(f"📨 받은 메시지: {text}")

            for prompt in fixed_prompts:
                text = text.replace(prompt, "").strip()

            if not text:
                continue

            response_text = ""

            if text == "start_order":
                response_text = "음성으로 주문하시겠습니까?"
                state.update({"step": "await_start", "cart": [], "finalized": False})

            elif state["step"] == "await_start":
                if is_positive(text):
                    response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
                    state["step"] = "await_menu"
                elif "아니" in text:
                    response_text = "일반 키오스크로 주문을 진행해주세요."
                    client_states.pop(websocket)

            elif state["step"] == "await_menu":
                menu_items = await sync_to_async(list)(MenuItem.objects.all())
                input_text = text.replace(" ", "").lower()
                matched_item = None
                for item in menu_items:
                    if item.name.replace(" ", "").lower() in input_text:
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
                        response_text = f"{matched_item.name}은 {state['price']}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요?"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        response_text = f"{matched_item.name}은 {state['price']}원입니다. 옵션 선택을 진행할까요?"
                        state["step"] = "confirm_options"
                else:
                    response_text = "죄송합니다. 다시 메뉴를 말씀해주세요."

            elif state["step"] == "confirm_options":
                if "아니" in text:
                    category = state["category"]
                    if category == "커피":
                        state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
                    elif category == "음료":
                        state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
                    elif category == "차":
                        state["options"] = {"size": "보통", "temp": "아이스"}
                    else:
                        state["options"] = {}
                    state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                    response_text = f"기본 옵션으로 {state['menu']}를 장바구니에 담았습니다. 추가 메뉴 있으신가요?"
                    state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                elif is_positive(text):
                    response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
                    state["step"] = "choose_size"
                else:
                    response_text = "옵션을 진행할까요? 네 또는 아니요로 말씀해주세요."

            elif state["step"] == "choose_size":
                cleaned_text = text.replace(" ", "")
                last_index_보통 = cleaned_text.rfind("보통")
                last_index_큰 = cleaned_text.rfind("큰")

                if last_index_보통 == -1 and last_index_큰 == -1:
                    response_text = "보통 또는 큰 사이즈 중 하나를 말씀해주세요."
                elif last_index_큰 > last_index_보통:
                    state["options"]["size"] = "큰"
                    state["price"] += 500
                else:
                    state["options"]["size"] = "보통"

                if state["category"] == "음료":
                    state["options"]["temp"] = "아이스"
                    response_text = "샷 추가하시겠습니까?"
                    state["step"] = "ask_shot"
                elif state["category"] == "차":
                    response_text = "핫 또는 아이스를 선택해주세요."
                    state["step"] = "choose_temp"
                else:
                    response_text = "핫 또는 아이스를 선택해주세요."
                    state["step"] = "choose_temp"

            elif state["step"] == "choose_temp":
                cleaned_text = text.replace(" ", "")
                last_index_아이스 = cleaned_text.rfind("아이스")
                last_index_핫 = max(cleaned_text.rfind("핫"), cleaned_text.rfind("따뜻"))

                if last_index_아이스 == -1 and last_index_핫 == -1:
                    response_text = "핫 또는 아이스 중 하나를 선택해주세요."
                elif last_index_아이스 > last_index_핫:
                    state["options"]["temp"] = "아이스"
                    if state["category"] == "차":
                        state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                        response_text = f"추가 메뉴 있으신가요?"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        response_text = "샷 추가하시겠습니까?"
                        state["step"] = "ask_shot"
                else:
                    state["options"]["temp"] = "핫"
                    if state["category"] == "차":
                        state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                        response_text = f"추가 메뉴 있으신가요?"
                        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
                    else:
                        response_text = "샷 추가하시겠습니까?"
                        state["step"] = "ask_shot"

            elif state["step"] == "ask_shot":
                if "아니" in text:
                    state["options"]["shot"] = "없음"
                elif is_positive(text):
                    response_text = "1번 추가는 +300원이고 2번 추가는 +600원입니다."
                    state["step"] = "choose_shot"
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    continue
                else:
                    response_text = "샷 추가 여부를 네 또는 아니요로 말씀해주세요."
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    continue

                state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})

            elif state["step"] == "choose_shot":
                if "2" in text or "두" in text or "2번" in text or "두번" in text:
                    state["options"]["shot"] = "2샷"
                    state["price"] += 600
                elif "1" in text or "한" in text or "1번" in text or "한번" in text:
                    state["options"]["shot"] = "1샷"
                    state["price"] += 300
                else:
                    state["options"]["shot"] = "없음"

                state["cart"].append({"name": state["menu"], "options": state["options"].copy(), "price": state["price"]})
                response_text = f"추가 메뉴 있으신가요?"
                state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})

            elif state["step"] == "confirm_additional":
                if "아니" in text:
                    items = state.get("cart", [])
                    item_lines = []
                    for item in items:
                        opt = item.get("options", {})
                        if not opt:
                            item_lines.append(item['name'])
                        else:
                            option_str = " ".join([opt[k] for k in ["size", "temp", "shot"] if k in opt])
                            item_lines.append(f"{item['name']} {option_str}".strip())
                    total_price = sum(item['price'] for item in items)
                    summary = ", ".join(item_lines)
                    response_text = f"주문하신 항목은: {summary}. 총 결제 금액은 {total_price}원입니다. 결제를 진행합니다."
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    await asyncio.sleep(5)
                    response_text = "결제가 완료되었습니다."
                    await websocket.send(response_text)
                    synthesize_speech(response_text)
                    state.update({"step": "completed", "finalized": True})
                    continue
                elif is_positive(text):
                    response_text = "원하시는 메뉴를 말씀해주세요."
                    state["step"] = "await_menu"
                else:
                    response_text = "추가 메뉴가 있으신가요? 네 또는 아니요로 말씀해주세요."

            else:
                response_text = "죄송합니다. 다시 말씀해주세요."

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
