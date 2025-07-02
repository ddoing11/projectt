import time
from .utils import is_positive
from .audio_handler import synthesize_speech


class OptionHandler:
    """메뉴 옵션 선택 처리"""
    
    async def handle_choose_size(self, websocket, cleaned_text, state):
        """사이즈 선택 처리"""
        if "큰" in cleaned_text:
            state["options"]["size"] = "큰"
            state["price"] += 500
        elif "보통" in cleaned_text or "기본" in cleaned_text:
            state["options"]["size"] = "보통"
        else:
            # 유효하지 않은 사이즈 응답 → 재질문 대기 상태로 전환
            state["step"] = "waiting_size_retry"
            state["size_prompt_time"] = time.time()
            return ""

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
            return ""
        
        return response_text

    async def handle_choose_temp(self, websocket, cleaned_text, state):
        """온도 선택 처리"""
        cold_keywords = ["아이스", "차가운", "찬거", "찬 거", "시원한", "시원"]
        hot_keywords = ["핫", "하트", "하", "하스", "합", "뜨거운", "따뜻한", "드거운", "다듯한"]
        
        if any(t in cleaned_text for t in cold_keywords):
            state["options"]["temp"] = "아이스"
        elif any(t in cleaned_text for t in hot_keywords):
            state["options"]["temp"] = "핫"
        else:
            # 유효하지 않은 응답 → 재질문 대기 상태로 전환
            state["step"] = "waiting_temp_retry"
            state["temp_prompt_time"] = time.time()
            return ""

        if state["category"] == "차":
            state["cart"].append({
                "name": state["menu"], 
                "options": state["options"].copy(), 
                "price": state["price"], 
                "total_price": state["price"]
            })
            response_text = f"추가 메뉴 있으신가요?"
            state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
        else:
            response_text = "샷 추가하시겠습니까?"
            state["step"] = "ask_shot"
            state["last_question"] = response_text
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
            return ""
        
        return response_text

    async def handle_ask_shot(self, websocket, cleaned_text, state):
        """샷 추가 여부 처리"""
        if "아니" in cleaned_text:
            state["options"]["shot"] = "없음"
            state["cart"].append({
                "name": state["menu"], 
                "options": state["options"].copy(), 
                "price": state["price"], 
                "total_price": state["price"]
            })
            response_text = f"추가 메뉴 있으신가요?"
            state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
        elif is_positive(cleaned_text):
            response_text = "1번 추가는 +300원이고 2번 추가는 +600원입니다."
            state["step"] = "choose_shot"
            state["last_question"] = response_text
            await websocket.send("mic_off")
            await websocket.send(response_text)
            await synthesize_speech(response_text, websocket)
            return ""
        else:
            state["step"] = "waiting_shot_retry"
            state["shot_prompt_time"] = time.time()
            return ""
        
        return response_text

    async def handle_choose_shot(self, websocket, cleaned_text, state):
        """샷 개수 선택 처리"""
        if any(x in cleaned_text for x in ["2", "두"]):
            state["options"]["shot"] = "2샷"
            state["price"] += 600
        elif any(x in cleaned_text for x in ["1", "한"]):
            state["options"]["shot"] = "1샷"
            state["price"] += 300
        else:
            # 유효하지 않은 응답이면 다시 묻기
            state["step"] = "waiting_shot_retry"
            state["shot_prompt_time"] = time.time()
            return ""

        state["cart"].append({
            "name": state["menu"], 
            "options": state["options"].copy(), 
            "price": state["price"], 
            "total_price": state["price"]
        })
        response_text = f"추가 메뉴 있으신가요?"
        state.update({"step": "confirm_additional", "menu": None, "options": {}, "price": 0})
        return response_text