import json
import asyncio
import threading
import time
from .audio_handler import synthesize_speech, play_ding
from .order_processor import prepare_cart_items
from .utils import is_positive, is_negative, clean_input


class SpecialMessageHandler:
    """특수 메시지 및 기타 상태 처리"""
    
    async def handle_special_messages(self, websocket, text, state):
        """특수 메시지 처리"""
        if text == "request_mic_on":
            print(f"🔁 클라이언트로부터 mic_on 요청 수신 → 전송 시도")
            if websocket.close_code is not None:
                print("❌ mic_on 요청 수신 → 하지만 WebSocket이 이미 닫힘")
            else:
                print("🔁 클라이언트로부터 mic_on 요청 수신 → 전송")
                await websocket.send("mic_on")
            return True

        elif text == "read_cart":
            await self._handle_read_cart(websocket, state)
            return True

        elif text == "resume_from_menu":
            print("🔁 클라이언트 재연결 → 메뉴 선택 상태로 복원됨")
            state["step"] = "await_menu"
            response_text = "음성 주문을 시작합니다. 어떤 메뉴를 원하세요?"
            await synthesize_speech(response_text, websocket, activate_mic=True)
            return True

        elif text == "request_summary_tts":
            prompt = state.get("cart_summary")
            if prompt:
                await websocket.send("mic_off")
                await synthesize_speech(prompt, websocket, activate_mic=True)
            return True

        elif text == "resume_from_pay":
            await self._handle_resume_from_pay(websocket, state)
            return True

        elif text == "start_order":
            await self._handle_start_order(websocket, state)
            return True

        elif text == "done_page_ready":
            print("✅ done 페이지 준비됨 → 결제 완료 멘트 출력")
            await synthesize_speech("결제가 완료되었습니다. 감사합니다.", websocket, activate_mic=False)
            return True

        return False

    async def handle_other_states(self, websocket, text, cleaned_text, state):
        """기타 상태 처리"""
        step = state.get("step")
        
        # 대기 상태들 처리
        if step == "waiting_additional_retry":
            return await self._handle_waiting_additional_retry(websocket, cleaned_text, state)
        elif step == "waiting_shot_retry":
            return await self._handle_waiting_shot_retry(websocket, state)
        elif step == "waiting_size_retry":
            return await self._handle_waiting_size_retry(websocket, state)
        elif step == "waiting_temp_retry":
            return await self._handle_waiting_temp_retry(websocket, state)
        elif step == "confirm_repeat_options":
            return await self._handle_confirm_repeat_options(websocket, cleaned_text, state)
        
        return ""

    async def _handle_read_cart(self, websocket, state):
        """장바구니 읽기 처리"""
        print("📥 read_cart 요청 수신됨")
        items, total = await prepare_cart_items(state)

        await websocket.send(json.dumps({
            "type": "cart_items",
            "items": items
        }, default=str))
        print("📤 cart_items 전송 완료:", items)

    async def _handle_resume_from_pay(self, websocket, state):
        """결제 페이지에서 복귀 처리"""
        print("🔁 pay_all 복귀 요청 수신 → 장바구니 요약 및 결제 질문 재출력")
        state["step"] = "confirm_payment"

        # 저장된 장바구니 요약 및 질문 불러오기
        summary = state.get("cart_summary", "")
        if summary:
            await synthesize_speech(summary.strip(), websocket, activate_mic=False)

        followup = state.get("last_question", "총 결제 금액은 ~원입니다. ")
        await synthesize_speech(followup.strip(), websocket, activate_mic=True)

    async def _handle_start_order(self, websocket, state):
        """주문 시작 처리"""
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
        
        
        # 3단계 음성 안내
        await websocket.send("mic_off")
        await synthesize_speech("음성으로 주문하시겠습니까?", websocket, activate_mic=False)
        threading.Thread(target=play_ding).start()
        await asyncio.sleep(0.1)
        await synthesize_speech("소리 이후에 말씀해주세요.", websocket, activate_mic=False)
        
        # 약간 쉬었다가
        await asyncio.sleep(0.2)

        # 음성 주문을 시작합니다. 띵 소리 2
        threading.Thread(target=play_ding).start()
        await asyncio.sleep(0.05)
        await websocket.send("mic_on")

    async def _handle_waiting_additional_retry(self, websocket, cleaned_text, state):
        """추가 주문 대기 재시도 처리"""
        from .order_processor import process_cart_summary
        
        cleaned = cleaned_text.strip().lower()
        print(f"📨 받은 메시지: {cleaned_text}, 현재 상태: {state['step']}, is_negative: {is_negative(cleaned)}")

        if is_positive(cleaned):
            await websocket.send("mic_off")
            response_text = "어떤 메뉴를 원하세요?"
            await synthesize_speech(response_text, websocket, activate_mic=True)
            state["step"] = "await_menu"
            return ""

        elif is_negative(cleaned):
            if state.get("path") == "/start":
                await websocket.send("set_resume_flag")

            await websocket.send("go_to_pay")
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

        # 아직도 인식 못했을 경우 → 대기 유지
        elapsed = time.time() - state.get("additional_prompt_time", 0)
        if elapsed >= 4:
            response_text = "추가 주문 여부를 다시 말씀해주세요."
            state["step"] = "confirm_additional"
            await websocket.send("mic_off")
            await synthesize_speech(response_text, websocket)
        
        await asyncio.sleep(1)
        return ""

    async def _handle_waiting_shot_retry(self, websocket, state):
        """샷 선택 대기 재시도 처리"""
        elapsed = time.time() - state.get("shot_prompt_time", 0)
        if elapsed >= 4:
            response_text = "샷 추가 여부를 다시 말씀해주세요. 네 또는 아니요로 대답해 주세요."
            state["step"] = "ask_shot"
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
        await asyncio.sleep(1)
        return ""

    async def _handle_waiting_size_retry(self, websocket, state):
        """사이즈 선택 대기 재시도 처리"""
        elapsed = time.time() - state.get("size_prompt_time", 0)
        if elapsed >= 4:
            response_text = "사이즈를 다시 말씀해주세요. 보통 또는 큰 사이즈 중 하나를 선택해주세요."
            state["step"] = "choose_size"
            state["last_question"] = response_text
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
        await asyncio.sleep(1)
        return ""
        
    async def _handle_waiting_temp_retry(self, websocket, state):
        """온도 선택 대기 재시도 처리"""
        elapsed = time.time() - state.get("temp_prompt_time", 0)
        if elapsed >= 4:
            response_text = "온도를 다시 말씀해주세요. 따듯한 것 또는 차가운 것로 대답해 주세요."
            state["step"] = "choose_temp"
            state["last_question"] = response_text
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
        await asyncio.sleep(1)
        return ""

    async def _handle_confirm_repeat_options(self, websocket, cleaned_text, state):
        """반복 주문 옵션 확인 처리"""
        from asgiref.sync import sync_to_async
        from kiosk.models import MenuItem
        
        print("🧪 confirm_repeat_options 단계 진입")
        print("🧪 응답 텍스트:", cleaned_text)

        # 시스템 질문이 다시 들어온 경우 → 무시
        if cleaned_text.strip() in ["같은옵션으로주문할까요"]:
            print("⚠️ 시스템 질문만 재인식됨 → 무시")
            return ""

        if is_positive(cleaned_text.strip()):
            item = state.get("last_repeat_item")
            if item:
                print("🧾 마지막 주문 옵션 복사:", item)
                
                if item["category"] == "디저트":
                    state["cart"].append({
                        "name": item["name"],
                        "options": {},
                        "price": item["price"], 
                        "total_price": item["price"],
                        "count": 1
                    })
                    response_text = f"{item['name']}을 담았습니다. 추가로 주문하시겠습니까?"
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True)
                    state["step"] = "confirm_additional"
                else:
                    state["cart"].append({
                        "name": item["name"],
                        "options": item["options"].copy(),
                        "total_price": item["price"],
                        "price": item["price"]
                    })
                    response_text = f"{item['name']}을(를) 동일한 옵션으로 하나 더 담았습니다. 추가로 주문하시겠습니까?"
                    await websocket.send("mic_off")
                    await synthesize_speech(response_text, websocket, activate_mic=True)
                    state["step"] = "confirm_additional"

                state.update({
                    "step": "confirm_additional",
                    "menu": None,
                    "options": {},
                    "price": 0
                })
                return ""

        elif is_negative(cleaned_text.strip()):
            # 이전 메뉴는 유지하지만 옵션만 다시 고를 수 있도록 설정
            repeat_item = state.get("last_repeat_item")
            if repeat_item:
                state["menu"] = repeat_item["name"]
                state["category"] = repeat_item.get("category") or state.get("category")
                
                # 가격은 기본 가격으로 초기화
                try:
                    item_obj = await sync_to_async(MenuItem.objects.get)(name=repeat_item["name"])
                    state["price"] = int(item_obj.price)
                    state["category"] = item_obj.category
                except MenuItem.DoesNotExist:
                    state["price"] = repeat_item.get("price", 0)

            # 옵션 선택 단계로 이동
            if state["category"] == "디저트":
                state["cart"].append({
                    "name": state["menu"],
                    "options": {},
                    "price": state["price"],
                    "total_price": state["price"],
                    "count": 1
                })
                response_text = f"{state['menu']}을 담았습니다. 추가로 주문하시겠습니까?"
                await websocket.send("mic_off")
                await synthesize_speech(response_text, websocket, activate_mic=True)
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
            return response_text

        else:
            # 유효하지 않은 응답이거나 시스템 질문 포함된 채 인식됨 → 재질문
            response_text = "같은 옵션으로 주문할까요? 네 또는 아니요로 말씀해주세요."
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
            return ""