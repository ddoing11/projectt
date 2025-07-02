import json
from collections import defaultdict
from .database import get_price_from_db


async def process_cart_summary(state):
    """장바구니 요약 생성"""
    counter = defaultdict(lambda: {"count": 0, "total_price": 0, "name": "", "options": ""})
    
    for item in state["cart"]:
        size = item["options"].get("size")
        temp = item["options"].get("temp")
        shot = item["options"].get("shot")
        
        opt_parts = []
        if size:
            opt_parts.append("사이즈 큰 거" if size == "큰" else f"사이즈 {size}")
        if temp:
            opt_parts.append(temp)
        if shot:
            opt_parts.append("샷 없음" if shot == "없음" else shot)

        opt_text = ", ".join(opt_parts)
        key = f"{item['name']}|{opt_text}"

        counter[key]["count"] += 1
        counter[key]["total_price"] += item["price"]
        counter[key]["name"] = item["name"]
        counter[key]["options"] = opt_text

    # 내역 요약
    summary = "주문 내역입니다:\n"
    total = 0
    
    for item in state.get("cart", []):
        name = item.get("name", "")
        options = item.get("options", {})
        count = item.get("count", 1)
        base_price = await get_price_from_db(name)
        
        # ✅ 옵션 기반 추가 가격 계산
        extra_price = 0
        size = options.get("size")
        shot = options.get("shot")

        if size == "큰":
            extra_price += 500
        if shot == "1샷":
            extra_price += 300
        elif shot == "2샷":
            extra_price += 600

        total_price = (base_price + extra_price) * count
        item["price"] = base_price + extra_price  # ✅ 단가 갱신
        item["total_price"] = total_price         # ✅ 총액 갱신

        option_text = ", ".join([f"{k}: {v}" for k, v in options.items()])
        summary += f"- {name} {option_text} {count}개에 {total_price:,}원\n"
        total += total_price

    final_prompt = f"{summary.strip()}\n총 결제 금액은 {total}원입니다.\n."
    return final_prompt


async def prepare_cart_items(state):
    """장바구니 아이템 준비"""
    items = []
    total = 0

    for item in state.get("cart", []):
        name = item.get("name")
        price = item.get("total_price", 0)
        options = item.get("options", {})
        count = item.get("count", 1)

        base_price = await get_price_from_db(name)

        # ✅ 옵션에 따른 추가 금액 계산
        extra_price = 0
        size = options.get("size")
        shot = options.get("shot")
                            
        if size == "큰":
            extra_price += 500
        if shot == "1샷":
            extra_price += 300
        elif shot == "2샷":
            extra_price += 600

        final_price = base_price + extra_price
        total_price = final_price * count

        # ✅ cart 내부에도 다시 반영
        item["price"] = final_price
        item["total_price"] = total_price

        # ✅ 전달할 JSON 항목 구성
        items.append({
            "name": name,
            "count": count,
            "price": final_price
        })

        total += total_price

    return items, total


def calculate_item_price(item_name, options, base_price):
    """개별 아이템 가격 계산 (옵션 포함)"""
    extra_price = 0
    size = options.get("size")
    shot = options.get("shot")

    if size == "큰":
        extra_price += 500
    if shot == "1샷":
        extra_price += 300
    elif shot == "2샷":
        extra_price += 600

    return base_price + extra_price


def create_cart_item(name, options, price, category="기타"):
    """장바구니 아이템 생성"""
    return {
        "name": name,
        "options": options.copy(),
        "price": price,
        "total_price": price,
        "count": 1,
        "category": category
    }