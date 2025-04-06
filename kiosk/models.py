from django.db import models

class Menu(models.Model):
    category = models.CharField(max_length=50, help_text="음료 카테고리")
    name = models.CharField(max_length=100, help_text="메뉴 이름")
    options = models.JSONField(default=lambda: {}, help_text="옵션")

    def __str__(self):
        return f"{self.category} - {self.name}"



class SpeechCommand(models.Model):
    input_text = models.CharField(max_length=255, unique=True) # "따듯하고 달지 않은 것"
    response_text = models.CharField(max_length = 255) # 녹차
    recommended = models.IntegerField(default = 0) # 추천된 횟수


class Cart(models.Model):
    menu_item = models.ForeignKey(Menu, on_delete=models.CASCADE)  # 장바구니에 담긴 메뉴
    option = models.CharField(max_length=50, choices=[("hot", "HOT"), ("ice", "ICE")])  # HOT/ICE 설정
    quantity = models.IntegerField(default=1)  # 기본 수량 1개
    ordered = models.BooleanField(default=False)  # 결제 완료 여부






