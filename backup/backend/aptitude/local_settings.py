# 현재 데이터베이스의 값을 입력한다.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'railway',
        'USER': 'root',
        'PASSWORD': 'VFYVyfhvTGZAyWeOlQPJmtXYqFlhVkBw',
        'HOST': 'gondola.proxy.rlwy.net',
        'PORT': '58532',
        'OPTIONS': {
            'charset': 'utf8mb4',
        },
    }
}


# settings.py에 있던 시크릿 키를 아래 ''안에 입력한다.
SECRET_KEY ='-5k2e1#i2+_b-@q*h$2w_!+4)i(7f1iqo5o0!5186w8pt^hgt_'

AZURE_SPEECH_KEY = 'AiWSx0WLMN1ZkyF6i4jjLlvmwq2Yiv2EtenQdIQTS9EUTlBMoxs0JQQJ99BDACNns7RXJ3w3AAAYACOGL55e'
AZURE_SPEECH_REGION = 'koreacentral'
