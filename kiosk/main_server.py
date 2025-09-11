import asyncio
import websockets
import os
import sys
import json
import time
from asgiref.sync import sync_to_async
from collections import defaultdict

# Django 설정
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.aptitude.settings")
import django
django.setup()

from kiosk.models import MenuItem
from kiosk.gpt_handler import get_chatgpt_response


class VoiceKioskServer:
    def __init__(self):
        self.clients = {}
        self.sessions = {}

    def create_initial_state(self):
        """초기 상태 생성"""
        return {
            "step": "init",
            "menu": None,
            "options": {},
            "price": 0,
            "category": None,
            "cart": [],
            "gpt_messages": [],
            "client_id": None,
            "path": None,
            "waiting_for_response": False,
            "last_question_time": 0
        }

    async def handle_client(self, websocket):
        """클라이언트 연결 처리"""
        client_id = id(websocket)
        self.clients[client_id] = {
            "websocket": websocket,
            "state": self.create_initial_state()
        }
        
        print(f"✅ 클라이언트 연결됨: {client_id}")
        
        try:
            async for message in websocket:
                await self.process_message(client_id, message)
        except websockets.exceptions.ConnectionClosed:
            print(f"❌ 클라이언트 연결 종료: {client_id}")
        finally:
            if client_id in self.clients:
                del self.clients[client_id]

    async def process_message(self, client_id, message):
        """메시지 처리"""
        if client_id not in self.clients:
            return
            
        websocket = self.clients[client_id]["websocket"]
        state = self.clients[client_id]["state"]
        
        print(f"📨 받은 메시지: {message}")
        
        # JSON 메시지 처리
        try:
            data = json.loads(message)
            await self.handle_json_message(websocket, state, data)
            return
        except json.JSONDecodeError:
            pass
        
        # 특수 메시지 처리
        if await self.handle_special_message(websocket, state, message):
            return
            
        # 일반 텍스트 메시지 처리
        await self.handle_text_message(websocket, state, message.strip())

    async def handle_json_message(self, websocket, state, data):
        """JSON 메시지 처리"""
        if data.get("type") == "page_info":
            client_id = data.get("client_id")
            path = data.get("path")
            
            state["client_id"] = client_id
            state["path"] = path
            
            print(f"📄 페이지 정보: {path}, client_id: {client_id}")
            
            # 세션 복원
            if client_id in self.sessions:
                restored_state = self.sessions[client_id]
                state.update(restored_state)
                state["path"] = path
            else:
                self.sessions[client_id] = state

        elif data.get("type") == "tts_ready":
            # 클라이언트에서 TTS 준비 완료 신호를 받음
            print("🔊 클라이언트 TTS 준비 완료됨")
            if state.get("pending_voice_flow"):
                print("🎬 지연된 음성 플로우 재개")
                await self._continue_voice_flow(websocket, state)

    async def handle_special_message(self, websocket, state, message):
        """특수 메시지 처리"""
        if message == "start_order":
            await self.start_voice_order(websocket, state)
            return True
            
        elif message == "resume_from_menu":
            await self.send_tts(websocket, "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?")
            state["step"] = "await_menu"
            return True
            
        elif message == "read_cart":
            await self.send_cart_items(websocket, state)
            return True
            
        elif message == "request_mic_on":
            await websocket.send("mic_on")
            return True
            
        return False

    async def handle_text_message(self, websocket, state, text):
        """텍스트 메시지 처리"""
        step = state.get("step")
        cleaned_text = self.clean_input(text)
        
        print(f"🧹 정제된 텍스트: '{cleaned_text}' (원본: '{text}')")
        print(f"📍 현재 상태: {step}")
        
        if step == "await_start":
            await self.handle_await_start(websocket, state, cleaned_text)
        elif step == "await_menu":
            await self.handle_await_menu(websocket, state, text, cleaned_text)
        elif step == "confirm_options":
            await self.handle_confirm_options(websocket, state, cleaned_text)
        elif step == "choose_size":
            await self.handle_choose_size(websocket, state, cleaned_text)
        elif step == "choose_temp":
            await self.handle_choose_temp(websocket, state, cleaned_text)
        elif step == "ask_shot":
            await self.handle_ask_shot(websocket, state, cleaned_text)
        elif step == "choose_shot":
            await self.handle_choose_shot(websocket, state, cleaned_text)
        elif step == "confirm_additional":
            await self.handle_confirm_additional(websocket, state, cleaned_text)
        elif step == "confirm_payment":
            await self.handle_confirm_payment(websocket, state, cleaned_text)

    async def start_voice_order(self, websocket, state):
        """음성 주문 시작 - 개선된 타이밍"""
        state.update({
            "step": "await_start",
            "cart": [],
            "menu": None,
            "options": {},
            "price": 0,
            "category": None
        })
        
        print("🎬 음성 주문 시작 - 순차적 실행")
        
        # 1단계: 마이크 끄고 첫 번째 TTS
        await websocket.send("mic_off")
        await self.send_tts(websocket, "음성으로 주문하시겠습니까?", activate_mic=False)
        
        # TTS 완료를 위한 충분한 대기 시간
        await asyncio.sleep(2.5)
        
        # 2단계: 첫 번째 딩 소리
        await self.send_ding(websocket)
        await asyncio.sleep(0.5)
        
        # 3단계: 두 번째 TTS
        await self.send_tts(websocket, "소리 이후에 말씀해주세요.", activate_mic=False)
        
        # 두 번째 TTS 완료 대기
        await asyncio.sleep(2.0)
        
        # 4단계: 두 번째 딩 소리
        await self.send_ding(websocket)
        await asyncio.sleep(0.3)
        
        # 5단계: 마이크 켜기
        await websocket.send("mic_on")
        print("✅ 음성 주문 플로우 완료")

    async def _continue_voice_flow(self, websocket, state):
        """TTS 준비 완료 후 음성 플로우 계속"""
        state["pending_voice_flow"] = False
        
        await asyncio.sleep(0.5)
        await self.send_ding(websocket)
        await asyncio.sleep(0.3)
        await self.send_tts(websocket, "소리 이후에 말씀해주세요.", activate_mic=False)
        await asyncio.sleep(2.0)
        await self.send_ding(websocket)
        await asyncio.sleep(0.3)
        await websocket.send("mic_on")

    async def handle_await_start(self, websocket, state, cleaned_text):
        """시작 대기 처리"""
        if self.is_positive(cleaned_text):
            await websocket.send("goto_menu")
            state["step"] = "await_menu"
        elif self.is_negative(cleaned_text):
            await self.send_tts(websocket, "일반 키오스크로 진행하세요.", activate_mic=False)
            await asyncio.sleep(2.0)
            await websocket.send("set_disable_voice")
            await websocket.send("go_to_order2")

    async def handle_await_menu(self, websocket, state, original_text, cleaned_text):
        """메뉴 선택 처리"""
        # 메뉴 매칭
        menu_items = await sync_to_async(list)(MenuItem.objects.all())
        matched_item = None
        
        for item in menu_items:
            item_name_clean = item.name.replace(" ", "").lower()
            if item_name_clean in cleaned_text.lower():
                matched_item = item
                print(f"🎯 메뉴 매칭됨: {item.name}")
                break
        
        # 주문 의도 확인
        order_keywords = ["주세요", "주문", "시킬게", "갖고갈게", "먹을게", "해주세요", "줘", "달라"]
        has_order_intent = any(keyword in cleaned_text for keyword in order_keywords)
        
        print(f"📋 매칭된 메뉴: {matched_item.name if matched_item else None}")
        print(f"📋 주문 의도: {has_order_intent}")
        
        if matched_item and (has_order_intent or len(cleaned_text) <= 10):
            await self.process_menu_selection(websocket, state, matched_item)
        else:
            # GPT 응답
            gpt_reply = await get_chatgpt_response(original_text, state["gpt_messages"])
            await self.send_tts(websocket, gpt_reply)

    async def process_menu_selection(self, websocket, state, item):
        """메뉴 선택 처리"""
        state.update({
            "menu": item.name,
            "price": int(item.price),
            "category": item.category,
            "options": {}
        })
        
        print(f"🍽️ 선택된 메뉴: {item.name}, 카테고리: {item.category}")
        
        if item.category == "디저트":
            # 디저트는 옵션 없이 바로 장바구니에 추가
            state["cart"].append({
                "name": item.name,
                "options": {},
                "price": state["price"],
                "count": 1
            })
            response_text = f"{item.name} {state['price']}원입니다. 장바구니에 담았습니다. 추가 주문하시겠습니까?"
            state["step"] = "confirm_additional"
        else:
            response_text = f"{item.name} {state['price']}원입니다. 옵션을 선택하시겠습니까?"
            state["step"] = "confirm_options"
        
        await self.send_tts(websocket, response_text)

    async def handle_confirm_options(self, websocket, state, cleaned_text):
        """옵션 확인 처리"""
        if self.is_positive(cleaned_text):
            state["step"] = "choose_size"
            await self.send_tts(websocket, "보통 또는 큰 사이즈를 선택해주세요. 큰 사이즈는 500원 추가됩니다.")
        else:
            # 기본 옵션으로 추가
            await self.add_to_cart_with_default_options(websocket, state)

    async def handle_choose_size(self, websocket, state, cleaned_text):
        """사이즈 선택 처리"""
        print(f"🔍 사이즈 선택 분석: '{cleaned_text}'")
        
        # 다양한 큰 사이즈 표현들
        large_keywords = ["큰", "크게", "큰거", "큰것", "큰사이즈", "라지", "large", "큰걸로", "큰것으로"]
        regular_keywords = ["보통", "기본", "작은", "스몰", "small", "레귤러", "regular", "보통으로", "기본으로"]
        
        if any(keyword in cleaned_text for keyword in large_keywords):
            state["options"]["size"] = "큰"
            state["price"] += 500
            print("✅ 큰 사이즈 선택됨")
        elif any(keyword in cleaned_text for keyword in regular_keywords):
            state["options"]["size"] = "보통"
            print("✅ 보통 사이즈 선택됨")
        else:
            # 명확하지 않은 경우 다시 질문
            print("❓ 사이즈 불명확, 재질문")
            await self.send_tts(websocket, "죄송합니다. 보통 사이즈 또는 큰 사이즈 중에서 명확히 말씀해주세요.")
            return
        
        # 다음 단계로
        if state["category"] in ["커피", "음료"]:
            state["step"] = "choose_temp"
            await self.send_tts(websocket, "따듯한 것 또는 차가운 것을 선택해주세요.")
        else:  # 차
            state["options"]["temp"] = "아이스"
            await self.add_to_cart_and_continue(websocket, state)

    async def handle_choose_temp(self, websocket, state, cleaned_text):
        """온도 선택 처리"""
        print(f"🔍 온도 선택 분석: '{cleaned_text}'")
        
        cold_keywords = ["아이스", "차가운", "시원한", "찬", "얼음", "콜드", "cold", "차갑게", "시원하게"]
        hot_keywords = ["핫", "뜨거운", "따뜻한", "더운", "hot", "따듯한", "뜨겁게", "따뜻하게"]
        
        if any(keyword in cleaned_text for keyword in cold_keywords):
            state["options"]["temp"] = "아이스"
            print("✅ 아이스 선택됨")
        elif any(keyword in cleaned_text for keyword in hot_keywords):
            state["options"]["temp"] = "핫"
            print("✅ 핫 선택됨")
        else:
            print("❓ 온도 불명확, 재질문")
            await self.send_tts(websocket, "따듯한 것 또는 차가운 것 중에서 명확히 말씀해주세요.")
            return
        
        if state["category"] == "차":
            await self.add_to_cart_and_continue(websocket, state)
        else:
            state["step"] = "ask_shot"
            await self.send_tts(websocket, "샷을 추가하시겠습니까?")

    async def handle_ask_shot(self, websocket, state, cleaned_text):
        """샷 추가 확인"""
        if self.is_negative(cleaned_text):
            state["options"]["shot"] = "없음"
            await self.add_to_cart_and_continue(websocket, state)
        elif self.is_positive(cleaned_text):
            state["step"] = "choose_shot"
            await self.send_tts(websocket, "1샷 추가는 300원, 2샷 추가는 600원입니다. 몇 샷을 추가하시겠습니까?")
        else:
            await self.send_tts(websocket, "샷 추가 여부를 네 또는 아니요로 말씀해주세요.")

    async def handle_choose_shot(self, websocket, state, cleaned_text):
        """샷 개수 선택"""
        print(f"🔍 샷 선택 분석: '{cleaned_text}'")
        
        if any(keyword in cleaned_text for keyword in ["2", "두", "이", "투"]):
            state["options"]["shot"] = "2샷"
            state["price"] += 600
            print("✅ 2샷 선택됨")
        elif any(keyword in cleaned_text for keyword in ["1", "한", "하나", "원"]):
            state["options"]["shot"] = "1샷"
            state["price"] += 300
            print("✅ 1샷 선택됨")
        else:
            state["options"]["shot"] = "없음"
            print("✅ 샷 없음으로 처리")
        
        await self.add_to_cart_and_continue(websocket, state)

    async def add_to_cart_with_default_options(self, websocket, state):
        """기본 옵션으로 장바구니 추가"""
        category = state["category"]
        if category in ["커피", "음료"]:
            state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
        elif category == "차":
            state["options"] = {"size": "보통", "temp": "아이스"}
        
        await self.add_to_cart_and_continue(websocket, state)

    async def add_to_cart_and_continue(self, websocket, state):
        """장바구니 추가 및 계속"""
        cart_item = {
            "name": state["menu"],
            "options": state["options"].copy(),
            "price": state["price"],
            "count": 1
        }
        
        state["cart"].append(cart_item)
        
        print(f"🛒 장바구니 추가: {cart_item}")
        
        state.update({
            "step": "confirm_additional",
            "menu": None,
            "options": {},
            "price": 0
        })
        
        await self.send_tts(websocket, "추가 주문하시겠습니까?")

    async def handle_confirm_additional(self, websocket, state, cleaned_text):
        """추가 주문 확인"""
        if self.is_positive(cleaned_text):
            state["step"] = "await_menu"
            await self.send_tts(websocket, "어떤 메뉴를 원하세요?")
        elif self.is_negative(cleaned_text):
            await self.proceed_to_payment(websocket, state)
        else:
            await self.send_tts(websocket, "추가 주문 여부를 네 또는 아니요로 말씀해주세요.")

    async def handle_confirm_payment(self, websocket, state, cleaned_text):
        """결제 확인"""
        if self.is_positive(cleaned_text):
            await websocket.send("popup_payment")
            await self.send_tts(websocket, "결제를 진행합니다.", activate_mic=False)
            await asyncio.sleep(3.0)
            await websocket.send("go_to_done")
            # 상태 초기화
            state.update(self.create_initial_state())
        elif self.is_negative(cleaned_text):
            await websocket.send("goto_start")
            state.update(self.create_initial_state())
        else:
            await self.send_tts(websocket, "결제를 진행할까요? 네 또는 아니요로 말씀해주세요.")

    async def proceed_to_payment(self, websocket, state):
        """결제 진행"""
        # 장바구니 요약 생성
        summary = await self.create_cart_summary(state)
        
        state["step"] = "confirm_payment"
        
        # 클라이언트로 카트 데이터 전송
        await websocket.send(json.dumps({
            "type": "cart_summary",
            "text": summary
        }))
        
        await websocket.send("go_to_pay")
        await self.send_tts(websocket, summary)

    async def create_cart_summary(self, state):
        """장바구니 요약 생성"""
        summary = "주문 내역입니다:\n"
        total = 0
        
        for item in state["cart"]:
            name = item["name"]
            options = item["options"]
            price = item["price"]
            count = item["count"]
            
            option_text = []
            if options.get("size"):
                option_text.append(f"사이즈 {options['size']}")
            if options.get("temp"):
                option_text.append(options["temp"])
            if options.get("shot") and options["shot"] != "없음":
                option_text.append(options["shot"])
            
            option_str = ", ".join(option_text) if option_text else "기본"
            item_total = price * count
            total += item_total
            
            summary += f"- {name} ({option_str}) {count}개: {item_total:,}원\n"
        
        summary += f"\n총 결제 금액은 {total:,}원입니다."
        return summary

    async def send_cart_items(self, websocket, state):
        """장바구니 아이템 전송"""
        items = []
        for item in state["cart"]:
            items.append({
                "name": item["name"],
                "count": item["count"],
                "price": item["price"]
            })
        
        await websocket.send(json.dumps({
            "type": "cart_items",
            "items": items
        }))

    async def send_tts(self, websocket, text, activate_mic=True):
        """TTS 메시지 전송"""
        await websocket.send(json.dumps({
            "type": "text_to_speech",
            "text": text,
            "activate_mic": activate_mic
        }))

    async def send_ding(self, websocket):
        """딩 소리 전송"""
        await websocket.send(json.dumps({
            "type": "play_ding"
        }))

    def clean_input(self, text):
        """입력 텍스트 정제"""
        # 기본적인 정제만 수행
        import re
        text = re.sub(r"[^\w가-힣\s]", "", text)
        text = text.strip().lower()
        return text

    def is_positive(self, text):
        """긍정 응답 확인"""
        positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "yes", "맞아", "어", "음", "엥"]
        return any(word in text for word in positive_words)

    def is_negative(self, text):
        """부정 응답 확인"""
        negative_words = ["아니", "싫어", "안돼", "노", "그만", "아니요", "안할래", "별로", "없어"]
        return any(word in text for word in negative_words)


async def main():
    server = VoiceKioskServer()
    port = int(os.environ.get("PORT", 8002))
    
    async with websockets.serve(server.handle_client, "0.0.0.0", port):
        print(f"✅ 음성 키오스크 서버가 포트 {port}에서 실행 중")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())