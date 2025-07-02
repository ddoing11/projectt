import asyncio
from asgiref.sync import sync_to_async
from kiosk.models import MenuItem

from .utils import is_positive, is_negative, is_order_expression, is_repeat_order
from .audio_handler import synthesize_speech
from .gpt_handler import get_chatgpt_response
from .database import ensure_mysql_connection


class OrderStateHandler:
    """주문 상태별 처리 로직"""
    
    async def handle_await_start(self, websocket, cleaned_text, state):
        """await_start 상태 처리"""
        if is_positive(cleaned_text):
            await websocket.send("goto_menu")
            await asyncio.sleep(0.3)
            return ""

        if not cleaned_text.strip():
            return ""
        
        short_ignore = ["오", "우", "이", "흠", "요"]
        if cleaned_text in short_ignore:
            return ""

        if is_negative(cleaned_text):
            response_text = "일반 키오스크로 진행하세요."
            await synthesize_speech(response_text, websocket, activate_mic=False)
            await asyncio.sleep(0.7)
            await websocket.send("set_disable_voice")
            await asyncio.sleep(0.1)
            await websocket.send("go_to_order2")
            return ""

        return ""

    async def handle_await_menu(self, websocket, text, cleaned_text, state):
        """await_menu 상태 처리"""
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.all())
        cleaned_user_text = cleaned_text.replace(" ", "").lower()

        matched_item = next(
            (item for item in menu_items if item.name.replace(" ", "").lower() in cleaned_user_text),
            None
        )

        # 반복 주문 감지
        if is_repeat_order(cleaned_user_text):
            return await self._handle_repeat_order(websocket, state)

        has_clear_order = is_order_expression(cleaned_user_text)
        is_exact_menu = matched_item and matched_item.name.replace(" ", "").lower() == cleaned_user_text

        if matched_item and (has_clear_order or is_exact_menu):
            return await self._handle_menu_selection(websocket, matched_item, state)
        else:
            # GPT로 질문 위임
            gpt_reply = await get_chatgpt_response(text, state["gpt_messages"])
            await websocket.send("mic_off")
            await websocket.send(gpt_reply)
            await synthesize_speech(gpt_reply, websocket)
            return ""

    async def _handle_repeat_order(self, websocket, state):
        """반복 주문 처리"""
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
        await synthesize_speech(response_text, websocket)
        return ""

    async def _handle_menu_selection(self, websocket, item, state):
        """메뉴 선택 처리"""
        state.update({
            "menu": item.name,
            "price": int(item.price),
            "category": item.category,
            "options": {},
            "count": 1
        })
        
        if item.category == "디저트":
            state["cart"].append({
                "name": item.name, 
                "options": {}, 
                "price": state["price"], 
                "total_price": item.price
            })
            response_text = f"{item.name} {state['price']}원입니다. 장바구니에 담았습니다. 추가 메뉴 있으신가요? 네 또는 아니요로 대답해주세요"
            state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
        else:
            response_text = f"{item.name} {state['price']}원입니다. 옵션 선택을 진행할까요?"
            state["step"] = "confirm_options"
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket, activate_mic=True)
            return ""
        
        return response_text

    async def handle_confirm_options(self, websocket, cleaned_text, state):
        """옵션 확인 상태 처리"""
        if is_positive(cleaned_text):
            response_text = "보통 또는 큰 사이즈 둘 중 하나를 선택해주세요. 큰 사이즈는 500원이 추가됩니다."
            state["step"] = "choose_size"
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket, activate_mic=True)
            return ""
        elif is_negative(cleaned_text):
            return await self._handle_default_options(websocket, state)
        else:
            return "옵션을 진행할까요? 네 또는 아니요로 말씀해주세요."

    async def _handle_default_options(self, websocket, state):
        """기본 옵션 처리"""
        category = state["category"]
        if category in ["커피", "음료"]:
            state["options"] = {"size": "보통", "temp": "아이스", "shot": "없음"}
        elif category == "차":
            state["options"] = {"size": "보통", "temp": "아이스"}
        else:
            state["options"] = {}
            
        state["cart"].append({
            "name": state["menu"], 
            "options": state["options"].copy(), 
            "price": state["price"], 
            "total_price": state["price"]
        })
        
        response_text = f"기본 옵션으로 {state['menu']}를 장바구니에 담았습니다. 추가로 주문하시겠습니까? 네 또는 아니요로 대답해주세요"
        await websocket.send("mic_off")
        await synthesize_speech(response_text, websocket, activate_mic=True)
        
        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
        return ""