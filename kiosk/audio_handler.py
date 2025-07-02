import asyncio
import threading
from playsound import playsound
from django.conf import settings
from azure.cognitiveservices.speech import (
    SpeechConfig, SpeechSynthesizer, AudioConfig, ResultReason
)
from azure.cognitiveservices.speech.audio import AudioOutputConfig


# TTS 및 오디오 설정
AZURE_SPEECH_KEY = settings.AZURE_SPEECH_KEY
AZURE_SPEECH_REGION = settings.AZURE_SPEECH_REGION
sound_path = "C:/SoundAssets/ding.wav"


def play_ding(should_play=True):
    """띵 소리 재생"""
    if should_play:
        playsound(sound_path)


async def synthesize_speech(text, websocket=None, activate_mic=True):
    """Azure TTS를 사용한 음성 합성 및 재생"""
    speech_config = SpeechConfig(subscription=AZURE_SPEECH_KEY, region=AZURE_SPEECH_REGION)
    audio_config = AudioOutputConfig(use_default_speaker=True)
    synthesizer = SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)

    result = synthesizer.speak_text_async(text).get()

    if result.reason == ResultReason.SynthesizingAudioCompleted:
        # ✅ 띵 소리는 activate_mic이 True일 때만 재생
        threading.Thread(target=play_ding, args=(activate_mic,)).start()
        
        if activate_mic and websocket:
            try:
                await asyncio.sleep(0.05)

                for attempt in range(5):
                    try:
                        await websocket.send("mic_on")
                        print("✅ mic_on 전송 성공")
                        break
                    except Exception as e:
                        print(f"⚠️ mic_on 전송 중 오류: {e} (재시도 {attempt + 1}/5)")
                        print(f"↪️ websocket 객체 상태: {websocket}, close_code: {getattr(websocket, 'close_code', 'N/A')}")
                        await asyncio.sleep(0.3)
                else:
                    print("❌ mic_on 전송 실패: 5번 시도 후도 실패")

            except Exception as e:
                print(f"⚠️ mic_on 전송 최종 실패: {e}")
                print(f"↪️ websocket 객체 상태: {websocket}, close_code: {getattr(websocket, 'close_code', 'N/A')}")

    return result.reason == ResultReason.SynthesizingAudioCompleted


async def send_text(websocket, message):
    """WebSocket으로 텍스트 전송"""
    await websocket.send(message)