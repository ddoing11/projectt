from openai import OpenAI
from django.conf import settings
from asgiref.sync import sync_to_async
from kiosk.models import MenuItem
from .database import ensure_mysql_connection


client = OpenAI(api_key=settings.OPENAI_API_KEY)


async def get_chatgpt_response(user_input, gpt_messages):
    """ChatGPT API를 통한 응답 생성"""
    
    # 메뉴 불러오기
    await ensure_mysql_connection()
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
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.filter(category=category))
    else:
        await ensure_mysql_connection()
        menu_items = await sync_to_async(list)(MenuItem.objects.all())

    menu_names = [item.name for item in menu_items]
    menu_list_text = ", ".join(menu_names)

    # GPT prompt용
    matched_menu = None
    for original, cleaned in zip(menu_items, menu_names_cleaned):
        if cleaned in user_cleaned or cleaned == user_cleaned:
            matched_menu = original.name
            break

    recommend_keywords = ["추천", "추천해줘", "뭐", "뭐가", "있어", "어울리는", "맞는", "날씨", "어떤", "고를까"]
    is_recommend_request = any(k in user_input.replace(" ", "").lower() for k in recommend_keywords)

    # 시스템 프롬프트 생성
    base_prompt = (
        f"절대 '나는 주문을 받을 수 없어'라는 말은 하지 마. "
        f"당신은 친절한 카페 직원입니다. 아래 메뉴 중에서만 설명하거나 추천해주세요. "
        f"메뉴 리스트: {menu_list_text} "
        "이외의 메뉴는 절대 언급하지 마세요. 손님이 메뉴 설명을 요청하면 해당 메뉴를 1문장으로 짧게 설명하고, "
        "추천을 요청하면 2개의 메뉴를 소개하고 각 한 문장씩 소개하세요. 주문은 받지 마세요."
        "맥락없는 소리 (ex: '음', '요' 등)은 무시하고 응답하지 마세요"
        "손님이 우리 카페에 없는 메뉴를 요청하면, 직접적으로 거절하지 말고 메뉴 리스트 안에서 비슷한 것을 친절하게 추천하세요."
        "손님이 영어로 말하면 너도 영어로 말해."
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
        model="gpt-4-turbo",
        messages=messages,
        max_tokens=200,
        temperature=0.7,
    )

    reply = response.choices[0].message.content.strip()
    gpt_messages.append({"role": "user", "content": user_input})
    gpt_messages.append({"role": "assistant", "content": reply})
    return reply