import json
from channels.generic.websocket import AsyncWebsocketConsumer
import azure.cognitiveservices.speech as speechsdk
import asyncio
from django.conf import settings
from asgiref.sync import async_to_sync
import wave

# 이 함수는 이미 위쪽에서 정의되어 있으므로 임포트할 필요 없음
def save_wav_from_bytes(audio_bytes, file_path):
    with wave.open(file_path, 'wb') as wf:
        wf.setnchannels(1)            # mono
        wf.setsampwidth(2)            # 16-bit
        wf.setframerate(16000)        # 16 kHz
        wf.writeframes(audio_bytes)

class AzureSTTConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.buffer = bytearray()
        self.recognizing = False
        self.loop = asyncio.get_event_loop()
        print("🎤 WebSocket 연결됨")

    async def disconnect(self, close_code):
        print("❌ 연결 종료")
        self.recognizing = False

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            self.buffer.extend(bytes_data)

            # 약 3초 이상 음성 데이터가 모였을 때만 처리
            if len(self.buffer) > 16000 * 2 and not self.recognizing:
                self.recognizing = True
                audio_bytes = bytes(self.buffer)
                self.buffer = bytearray()

                await self.loop.run_in_executor(None, self.recognize_and_send, audio_bytes)
                self.recognizing = False

    # 이 안에서 Azure 음성 인식 처리
    def recognize_and_send(self, audio_bytes):
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            save_wav_from_bytes(audio_bytes, tmp.name)
            tmp_path = tmp.name

        speech_config = speechsdk.SpeechConfig(
            subscription=settings.AZURE_SPEECH_KEY,
            region=settings.AZURE_SPEECH_REGION
        )
        audio_config = speechsdk.AudioConfig(filename=tmp_path)
        recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)

        result = recognizer.recognize_once()
        print("📝 인식 결과:", result.text)

        if result.reason == speechsdk.ResultReason.RecognizedSpeech:
            async_to_sync(self.send)(text_data=json.dumps({'text': result.text}))
