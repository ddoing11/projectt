import json
from channels.generic.websocket import AsyncWebsocketConsumer
import tempfile
import whisper
import aiofiles
import numpy as np

class STTConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        pass

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                temp_audio.write(bytes_data)
                temp_audio_path = temp_audio.name

            model = whisper.load_model("base")
            result = model.transcribe(temp_audio_path)
            text = result["text"]

            await self.send(text_data=json.dumps({"text": text}))

class AudioConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        print("✅ 클라이언트 WebSocket 연결됨")

    async def disconnect(self, close_code):
        print("❌ 연결 종료")

    async def receive(self, text_data=None, bytes_data=None):
        print("🎧 오디오 데이터 받음")
        await self.send(text_data=json.dumps({
            "text": "음성 인식 결과 (모의)"
        }))