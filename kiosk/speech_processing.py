# WebRTC로 사용자의 음성을 실시간으로 녹음하고 whisper api로 STT 변환

import openai

OPENAI_API_KEY = "내 위스퍼 api 키 삽입"

def transcribe_audio(audio_file):
     openai.api_key = OPENAI_API_KEY

     response = openai.Audio.transcribe(
        model = "whisper-1",
        file = audio_file
     )

     return response['text']

