from openai import OpenAI
from django.conf import settings
from asgiref.sync import sync_to_async
from kiosk.models import MenuItem

client = OpenAI(api_key=settings.OPENAI_API_KEY)

@sync_to_async
def ensure_mysql_connection():
    from django.db import connection
    from django.db.utils import OperationalError
    try:
        connection.cursor()
    except OperationalError:
        connection.close()

async def get_chatgpt_response(user_input, gpt_messages):
    """ChatGPT를 사용한 메뉴 추천 및 질문 응답"""
    
    # DB 연결 확인
    await ensure_mysql_connection()
    
    # 메뉴 불러오기
    menu_items = await sync_to_async(list)(MenuItem.objects.all())
    
    # 카테고리 판별
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

    # 필터링된 메뉴 불러오기
    if category:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.filter(category=category))
    
    menu_names = [item.name for item in menu_items]
    menu_list_text = ", ".join(menu_names)

    # 메뉴 매칭 확인
    matched_menu = None
    for item in menu_items:
        item_cleaned = item.name.replace(" ", "").lower()
        if item_cleaned in user_cleaned or item_cleaned == user_cleaned:
            matched_menu = item.name
            break

    # 추천 요청 확인
    recommend_keywords = ["추천", "추천해줘", "뭐", "뭐가", "있어", "어울리는", "맞는", "날씨", "어떤", "고를까"]
    is_recommend_request = any(k in user_cleaned for k in recommend_keywords)

    # 시스템 프롬프트 생성
    if matched_menu:
        # 특정 메뉴에 대한 질문
        system_prompt = (
            f"{matched_menu}에 대해 손님이 궁금해합니다. "
            f"맛이나 특징을 1-2문장으로 간결하게 설명해주세요. "
            f"추천은 하지 마세요. 예: '{matched_menu}는 달콤하고 부드러운 맛의 음료입니다.'"
        )
    elif is_recommend_request:
        # 추천 요청
        system_prompt = (
            f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
            f"메뉴 리스트: {menu_list_text} "
            f"이외의 메뉴는 절대 언급하지 마세요. "
            f"추천을 요청하면 2개의 메뉴를 소개하고 각 한 문장씩 소개하세요. "
            f"주문은 받지 마세요. 간결하고 친근하게 답변해주세요."
        )
    else:
        # 일반적인 응답
        system_prompt = (
            f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
            f"메뉴 리스트: {menu_list_text} "
            f"손님이 우리 카페에 없는 메뉴를 요청하면, 직접적으로 거절하지 말고 "
            f"메뉴 리스트 안에서 비슷한 것을 친절하게 추천하세요. "
            f"맥락없는 소리 (ex: '음', '요' 등)은 무시하고 응답하지 마세요. "
            f"간결하고 친근하게 답변해주세요."
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input}
    ]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=150,
            temperature=0.7,
        )

        reply = response.choices[0].message.content.strip()
        
        # 메시지 히스토리에 추가
        gpt_messages.append({"role": "user", "content": user_input})
        gpt_messages.append({"role": "assistant", "content": reply})
        
        return reply

    except Exception as e:
        print(f"❌ GPT API 오류: {e}")
        return "죄송합니다. 현재 추천 서비스에 문제가 있습니다. 메뉴에서 직접 선택해주세요."