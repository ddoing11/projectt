import asyncio
import threading
from playsound import playsound
from django.conf import settings
from azure.cognitiveservices.speech import (
    SpeechConfig, SpeechSynthesizer, AudioConfig, ResultReason
)
from azure.cognitiveservices.speech.audio import AudioOutputConfig
import base64
import json


# TTS 및 오디오 설정
AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION
sound_path = "C:/SoundAssets/ding.wav"


def play_ding(should_play=True):
    """띵 소리 재생"""
    if should_play:
        playsound(sound_path)


async def synthesize_speech(text, websocket=None, activate_mic=True):
    """Azure TTS를 사용한 음성 합성 및 클라이언트로 전송"""
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    # 서버에서 소리가 나지 않도록 None으로 설정하여 메모리로 음성 데이터를 받습니다.
    audio_config = None 
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    result = synthesizer.speak_text_async(text).get()

    if result.reason == ResultReason.SynthesizingAudioCompleted:
        # 음성 데이터를 base64로 인코딩
        audio_bytes = result.audio_data
        b64_audio = base64.b64encode(audio_bytes).decode('utf-8')
        
        # WebSocket으로 오디오 데이터 전송
        if websocket:
            try:
                # activate_mic 정보도 함께 보내 클라이언트가 mic_on을 보낼지 결정하도록 합니다.
                await websocket.send(json.dumps({"type": "tts_audio", "data": b64_audio, "activate_mic": activate_mic}))
                print("✅ TTS 오디오 데이터 전송 성공")
            except Exception as e:
                print(f"⚠️ TTS 오디오 데이터 전송 중 오류: {e}")

    return result.reason == ResultReason.SynthesizingAudioCompleted


async def send_text(websocket, message):
    """WebSocket으로 텍스트 전송"""
    await websocket.send(message)