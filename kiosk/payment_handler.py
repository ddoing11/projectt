import json
import asyncio
from .utils import is_positive, is_negative, fuzzy_remove_question
from .audio_handler import synthesize_speech, send_text
from .order_processor import process_cart_summary


class PaymentHandler:
    """결제 관련 처리"""
    
    async def handle_confirm_additional(self, websocket, cleaned_text, state):
        """추가 주문 확인 처리"""
        cleaned = cleaned_text.strip().lower()
        print(f"📨 받은 메시지: {cleaned_text}, 현재 상태: {state['step']}, is_negative: {is_negative(cleaned)}")

        if is_positive(cleaned_text):
            await websocket.send("mic_off")
            response_text = "어떤 메뉴를 원하세요?"
            await synthesize_speech(response_text, websocket, activate_mic=True)
            state["step"] = "await_menu"
            return ""

        elif is_negative(cleaned_text):
            return await self._proceed_to_payment(websocket, state)
        
        else:
            # 8초간 대기 후 재질문
            state["step"] = "waiting_confirm_additional"
            state["last_question"] = "추가 주문 여부를 네 또는 아니요로 말씀해주세요."

            async def delayed_reprompt():
                await asyncio.sleep(8)
                if state["step"] == "waiting_confirm_additional":
                    await websocket.send("mic_off")
                    await synthesize_speech(state["last_question"], websocket)

            asyncio.create_task(delayed_reprompt())
            return ""

    async def handle_confirm_payment(self, websocket, cleaned_text, state):
        """결제 확인 처리"""
        if cleaned_text in ["pay_all_ready", "read_cart", "request_mic_on"]:
            print(f"⚠️ 시스템 메시지 무시됨: {cleaned_text}")
            return ""

        cleaned = fuzzy_remove_question(cleaned_text, state.get("last_question", "")).strip().lower()
        
        print(f"🧼 원본 응답: {cleaned_text}")
        print(f"🧹 정제 후 응답: {cleaned}")
        print(f"✅ 긍정 인식 여부: {is_positive(cleaned)}")

        if is_positive(cleaned) and state["step"] in ["confirm_payment", "waiting_payment_retry"]:
            return await self._process_payment(websocket, state)

        elif is_negative(cleaned):
            return await self._cancel_payment(websocket, state)

        else:
            return await self._retry_payment_question(websocket, state)

    async def _proceed_to_payment(self, websocket, state):
        """결제 단계로 진행"""
        if state.get("path") == "/start":
            await websocket.send("set_resume_flag")

        await send_text(websocket, "go_to_pay")
        state["step"] = "confirm_payment"

        # 주문 요약 및 결제 멘트 생성
        final_prompt = await process_cart_summary(state)
        
        state["step"] = "confirm_payment"
        state["last_question"] = final_prompt
        state["cart_summary"] = final_prompt

        print("📤 cart_summary 텍스트 전송 중:", final_prompt)
        await websocket.send(json.dumps({
            "type": "cart_summary",
            "text": final_prompt
        }))
        print("📤 cart_summary 전송 완료:", final_prompt)

        await websocket.send("go_to_pay")
        await websocket.send("mic_off")
        await synthesize_speech(final_prompt, websocket, activate_mic=True)
        return ""

    async def _process_payment(self, websocket, state):
        """결제 처리 실행"""
        print("💳 결제 확정 → 팝업 실행")
        state["step"] = "payment_in_progress"

        try:
            await websocket.send("popup_payment")
            print("📨 popup_payment 메시지 전송됨")
        except Exception as e:
            print(f"❌ popup_payment 전송 실패: {e}")

        final_announce = "결제를 진행합니다."
        await websocket.send(final_announce)
        await synthesize_speech(final_announce, websocket, activate_mic=False)

        await asyncio.sleep(5)
        
        print("✅ go_to_done 메시지 전송됨")
        await websocket.send("go_to_done")
        await asyncio.sleep(1)    

        # 상태 초기화
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
        return ""

    async def _cancel_payment(self, websocket, state):
        """결제 취소 처리"""
        if state.get("step") in ["confirm_payment", "waiting_payment_retry"]:
            print("🛑 유저가 결제 거부 → 시작 페이지로 이동")
            await websocket.send("goto_start")

            # 상태 초기화
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
        return ""

    async def _retry_payment_question(self, websocket, state):
        """결제 질문 재시도"""
        print(f"📨 수신된 응답: 현재 상태: {state['step']}")
        
        # 여기서만 재질문 필요
        retry_text = "결제를 진행할까요? 네 또는 아니요로 말씀해주세요."
        state["step"] = "waiting_payment_retry"
        state["last_question"] = retry_text

        await websocket.send("mic_off")
        await synthesize_speech(retry_text, websocket, activate_mic=False)
        await asyncio.sleep(0.2)
        await websocket.send("mic_on")  

        # 8초 후 응답 없으면 재질문
        async def delayed_payment_retry():
            await asyncio.sleep(8)
            if state["step"] == "waiting_payment_retry":
                print("⏱️ 응답 없음 → 결제 재질문 출력")
                await asyncio.sleep(1)

                # 마지막 질문과 다르면 (= 이미 응답해서 진행 중이면) 재질문 X
                if state.get("last_question") != retry_text:
                    print("⛔ 상태 변경됨 → 재질문 생략")
                    return
                
                await websocket.send("mic_off")
                await synthesize_speech(retry_text, websocket, activate_mic=True)

        asyncio.create_task(delayed_payment_retry())
        return ""