import difflib
import re
from difflib import SequenceMatcher


def is_positive(text):
    """긍정 응답 감지"""
    text = text.strip().lower()
    positive_words = ["네", "응", "예", "그래", "좋아", "오케이", "웅", "ㅇㅇ", "좋습니다", "그렇죠", "네네", "예스", "예쓰", "yes", "응응", "엉", "근데", "에", "이때"]

    # 완전 일치
    if text in positive_words:
        return True

    # 마지막 1~3글자가 긍정어로 끝나는 경우
    for word in positive_words:
        if text.endswith(word):
            return True

    return match_fuzzy(text, positive_words)


def is_negative(text):
    """부정 응답 감지"""
    negative_words = ["아니", "싫어", "안돼", "노", "그만", "아니요", "안할래"]
    return any(word in text for word in negative_words) or match_fuzzy(text, negative_words)


def match_fuzzy(text, candidates):
    """퍼지 매칭"""
    for word in candidates:
        ratio = difflib.SequenceMatcher(None, text, word).ratio()
        if ratio > 0.6:
            return True
    return False


def has_order_intent(text):
    """주문 의도 감지"""
    order_keywords = ["주세요", "주문", "먹고", "마시고", "갖고", "주라", "하고", "시킬게", "시키고", "줘", "할래"]
    return any(k in text for k in order_keywords)


def clean_input(text):
    """입력 텍스트 정제"""
    original_text = text  # 백업
    original_cleaned = text.strip().lower()

    text = re.sub(r"[^\w가-힣]", "", text)
    text = text.replace(" ", "").lower()
    
    # 불필요한 끝말 제거 (예: 선택해주세요, 말씀해주세요 등)
    system_phrases = ["선택해주세요", "말씀해주세요", "대답해주세요", "해주세요"]
    for phrase in system_phrases:
        if text.endswith(phrase):
            text = text[: -len(phrase)]

    question_prefixes = [
        "음성으로주문하시겠습니까", "음성주문을시작합니다", "어떤메뉴를원하세요",
        "다시메뉴를말씀해주세요", "다시말씀해주세요",
        "같은옵션으로주문할까요", "옵션을진행할까요", "아메리카노다시주문하시겠어요", "사 추가하시겠습니까?",
        "같은옵션으로주문할까요네또는아니요로말씀해주세요",  # 완전한 문장도 포함
        "옵션을진행할까요네또는아니요로말씀해주세요", "4 추가하시겠습니다 ", "동일한 옵션으로 하나 더 담을까요", 
        "추가 주문 여부를 다시 말씀해 주세요", "메뉴 있으신가요", "음성으로주문하시겠습니다", "차 추가하시겠습니까", 
        "사추가여부를다시", "사추가 여부를 다시 말씀해 주세요", "사 추가하시겠습니다", "큰 사이즈는 500원이 추가됩니다", 
        "2,500원입니다", "어떤 메뉴를 원하세요", "간단한 식사 대용으로도 좋습니다", "큰 사이즈는 500원이 추가됩니다", 
        "결제를 진행할까요", "결제를 진행할까요?", "있으신가요"
    ]
    
    # ✅ 시스템 질문 유사 시작문 제거
    for _ in range(3):
        for phrase in question_prefixes:
            if text.startswith(phrase):
                print(f"🔍 시스템 문장 제거됨: {phrase}")
                text = text[len(phrase):]

    # ✅ 끝 문장도 잘라내기
    SYSTEM_SUFFIXES = [
        "네또는아니요로대답해주세요",
        "다시말씀해주세요네",
        "네또는아니요로말씀해주세요",
        "네또는아니요로답해주세요"
    ]
    for suffix in SYSTEM_SUFFIXES:
        if text.endswith(suffix):
            print(f"🔚 끝 문장 제거됨: {suffix}")
            text = text[: -len(suffix)]

    # ✅ 만약 제거 후 비어 있고, 원본도 시스템 질문이면 무시 (빈 텍스트 반환)
    if not text.strip():
        all_phrases = question_prefixes + SYSTEM_SUFFIXES
        for p in all_phrases:
            if original_cleaned.startswith(p) or original_cleaned.endswith(p):
                print(f"🛑 입력이 시스템 문장으로만 구성됨 → 무시 대상")
                return ""
        # 그렇지 않다면 원본 유지
        return original_text

    # ✅ 흔한 패턴 정리
    system_phrases = ["선택해주세요", "말씀해주세요", "대답해주세요", "해주세요"]
    for phrase in system_phrases:
        if text.endswith(phrase):
            text = text[: -len(phrase)]

    for j in ["을", "를", "이", "가", "은", "는", "에서", "로", "으로", "도", "만", "께", "한테", "에게", "랑", "하고"]:
        if text.endswith(j):
            text = text[:-len(j)]
            break
    return text


def strip_gpt_response_prefix(text, last_gpt_reply):
    """GPT 응답 접두사 제거"""
    if not last_gpt_reply:
        return text
    gpt_clean = clean_input(last_gpt_reply)
    text_clean = clean_input(text)

    if text_clean.startswith(gpt_clean[:20]):  # 앞 20자 유사성 검사
        print("🔍 GPT 응답 앞부분 포함 → 제거 시도")
        return text_clean.replace(gpt_clean, "").strip()
    return text


def fuzzy_remove_question(cleaned_text, last_question):
    """퍼지 매칭으로 질문 제거"""
    if not last_question or len(cleaned_text) <= 2:
        return cleaned_text  # ➤ 응답이 짧으면 제거하지 않음

    q_cleaned = clean_input(last_question)
    ratio = SequenceMatcher(None, cleaned_text, q_cleaned).ratio()

    if ratio > 0.85 and q_cleaned in cleaned_text:
        result = cleaned_text.replace(q_cleaned, "").strip()
        if result == "":
            # ⚠️ 질문만 남아 응답이 사라지면 제거하지 않고 원문 유지
            print("⚠️ 질문 제거 후 응답이 사라짐 → 제거하지 않음")
            return cleaned_text
        print(f"🧽 시스템 질문과 유사도 {ratio:.2f} → 질문 제거됨")
        return result

    return cleaned_text


def is_order_expression(text):
    """주문 표현 감지"""
    order_phrases = [
        "주세요", "주문할게요", "시킬게요", "갖고갈게요",
        "먹을게요", "살게요", "할게요", "줘", "주라", "줄래",
        "도하나주세요", "하나주세요", "더주세요"
    ]
    
    text_clean = text.replace(" ", "").lower()
    
    for phrase in order_phrases:
        if phrase in text_clean:
            return True
        if difflib.SequenceMatcher(None, text_clean, phrase).ratio() > 0.7:
            return True
    return False


def is_repeat_order(text):
    """반복 주문 감지"""
    repeat_keywords = [
        "같은걸로", "같은거", "그걸로", "그거", "방금", "또하나", "하나더", "다시",
        "같은거하나더", "같은메뉴", "아까", "한번더", "이전주문", "전에주문한거", "이전과같은"
    ]

    text_clean = text.replace(" ", "").lower()
    return any(k in text_clean for k in repeat_keywords)