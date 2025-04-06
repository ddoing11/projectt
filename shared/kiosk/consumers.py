import json
from channels.generic.websocket import AsyncWebsocketConsumer
import azure.cognitiveservices.speech as speechsdk
import asyncio
from django.conf import settings
from asgiref.sync import async_to_sync


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

    def recognize_and_send(self, audio_bytes):
        # temp 파일로 저장
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(audio_bytes)
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
