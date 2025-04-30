from django.db import models

class MenuItem(models.Model):
    category = models.CharField(max_length=20)  # 커피, 음료, 차, 디저트
    name = models.CharField(max_length=50)      # 메뉴 이름
    description = models.CharField(max_length=500, blank=True)  # 메뉴 설명
    price = models.DecimalField(max_digits=10, decimal_places=2)  # 가격
    order_count = models.IntegerField(default=0)  # 추천 또는 선택된 횟수

    def __str__(self):
        return f"{self.name} ({self.category}) - {self.price}원"
