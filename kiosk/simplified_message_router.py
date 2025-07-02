import json
import asyncio
import threading
from .state_manager import StateManager
from .order_state_handler import OrderStateHandler
from .option_handler import OptionHandler
from .special_message_handler import SpecialMessageHandler
from .payment_handler import PaymentHandler
from .utils import clean_input, fuzzy_remove_question, strip_gpt_response_prefix
from .audio_handler import play_ding, synthesize_speech  # synthesize_speech 추가


class SimplifiedMessageRouter:
    """간소화된 메시지 라우터 - 각 핸들러에 위임"""
    
    def __init__(self):
        self.state_manager = StateManager()
        self.order_handler = OrderStateHandler()
        self.option_handler = OptionHandler()
        self.special_handler = SpecialMessageHandler()
        self.payment_handler = PaymentHandler()

    async def handle_connection(self, websocket):
        """새 클라이언트 연결 처리"""
        print("🔗 클라이언트 연결됨")
        return self.state_manager.add_client(websocket)

    async def cleanup_connection(self, websocket):
        """연결 정리"""
        self.state_manager.remove_client(websocket)

    async def process_message(self, websocket, message):
        """메시지 처리 메인 로직"""
        state = self.state_manager.get_state(websocket)
        if not state:
            return

        text = message.strip()
        print(f"📨 받은 메시지: {text}")

        # 1. 특수 메시지 처리
        if await self.special_handler.handle_special_messages(websocket, text, state):
            return

        # 2. JSON 메시지 처리
        if await self._handle_json_messages(websocket, message, state):
            return

        # 3. 일반 텍스트 메시지 처리
        await self._handle_text_messages(websocket, text, state)

    async def _handle_json_messages(self, websocket, message, state):
        """JSON 메시지 처리"""
        try:
            data = json.loads(message)
            
            # TTS 요청 처리 추가
            if data.get("type") == "text_to_speech":
                text = data.get("text", "음성으로 주문하시겠습니까?")
                print(f"🎤 TTS 요청: {text}")
                
                try:
                    await synthesize_speech(text, websocket, activate_mic=True)
                    print("✅ TTS 처리 완료")
                except Exception as e:
                    print(f"❌ TTS 처리 오류: {e}")
                return True
                
            elif data.get("action") == "tts":
                text = data.get("message", "음성으로 주문하시겠습니까?")
                print(f"🎤 TTS 요청 (형식2): {text}")
                
                try:
                    await synthesize_speech(text, websocket, activate_mic=True)
                    print("✅ TTS 처리 완료")
                except Exception as e:
                    print(f"❌ TTS 처리 오류: {e}")
                return True
            
            # 기존 page_info 처리
            elif data.get("type") == "page_info":
                client_id = data.get("client_id")
                path = data.get("path")
                
                print(f"📄 클라이언트 페이지 경로: {path}, client_id: {client_id}")
                
                if path == "/order" and not state.get("disable_voice"):
                    await websocket.send("mic_on")

                # 세션 복원
                restored_state = self.state_manager.restore_session(client_id, websocket)
                restored_state["path"] = path
                return True
                
        except json.JSONDecodeError:
            pass
            
        return False

    async def _handle_text_messages(self, websocket, text, state):
        """일반 텍스트 메시지 처리"""
        # 텍스트 정제
        cleaned_text = clean_input(text)
        cleaned_text = fuzzy_remove_question(cleaned_text, state.get("last_question", ""))
        last_gpt_reply = state["gpt_messages"][-1]["content"] if state["gpt_messages"] else ""
        cleaned_text = strip_gpt_response_prefix(cleaned_text, last_gpt_reply)

        # 상태별 처리 위임
        response_text = await self._route_to_handler(websocket, text, cleaned_text, state)

        # 응답 전송
        if response_text:
            state["last_question"] = response_text
            await websocket.send(response_text)
            # TTS는 각 핸들러에서 처리

    async def _route_to_handler(self, websocket, text, cleaned_text, state):
        """상태에 따라 적절한 핸들러로 라우팅"""
        step = state.get("step")
        
        # 주문 상태 처리
        if step == "await_start":
            return await self.order_handler.handle_await_start(websocket, cleaned_text, state)
        elif step == "await_menu":
            return await self.order_handler.handle_await_menu(websocket, text, cleaned_text, state)
        elif step == "confirm_options":
            return await self.order_handler.handle_confirm_options(websocket, cleaned_text, state)
        
        # 옵션 선택 처리
        elif step == "choose_size":
            return await self.option_handler.handle_choose_size(websocket, cleaned_text, state)
        elif step == "choose_temp":
            return await self.option_handler.handle_choose_temp(websocket, cleaned_text, state)
        elif step == "ask_shot":
            return await self.option_handler.handle_ask_shot(websocket, cleaned_text, state)
        elif step == "choose_shot":
            return await self.option_handler.handle_choose_shot(websocket, cleaned_text, state)
        
        # 결제 관련 처리
        elif step in ["confirm_additional", "waiting_confirm_additional"]:
            return await self.payment_handler.handle_confirm_additional(websocket, cleaned_text, state)
        elif step in ["confirm_payment", "waiting_payment_retry"]:
            return await self.payment_handler.handle_confirm_payment(websocket, cleaned_text, state)
        
        # 기타 특수 상태들은 special_handler에서 처리
        else:
            return await self.special_handler.handle_other_states(websocket, text, cleaned_text, state)