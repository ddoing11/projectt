import openai

from .models import MenuItem

OPENAI_API_KEY = "your-chatgpt-api-key"

def get_chatbot_response(user_input):
     # ChatGPT API 요청
     openai.api_key = OPENAI_API_KEY

     response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "너는 카페 키오스크 봇임. 아래 메뉴 리스트 안에서만 추천해야 함."},
            {"role": "user", "content": user_input}
        ],
        api_key=OPENAI_API_KEY
     )
    
     chatbot_response = response['choices'][0]['message']['content']

    # DB에 저장
     existing_command = SpeechCommand.objects.filter(input_text=user_input).first()
     if not existing_command:
         SpeechCommand.objects.create(input_text=user_input, response_text=chatbot_response, recommended=1)
    
     return chatbot_response
