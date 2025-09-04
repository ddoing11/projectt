# run_servers.py
import subprocess
import os
import sys
from pathlib import Path

# 프로젝트 루트 경로 (이 파일이 위치한 폴더)
ROOT = Path(__file__).resolve().parent

def start_stt_server():
    """STT WebSocket 서버 실행: kiosk/stt_ws_server.py"""
    # STT 서버는 기본적으로 환경변수 PORT가 없으면 8002 포트를 사용합니다.
    env = os.environ.copy()
    # 필요하면 다른 포트를 지정할 수 있습니다. 예: env["PORT"] = "8002"
    stt_path = ROOT / "kiosk" / "stt_ws_server.py"
    print(f"🔊 STT 서버 실행: {stt_path}")
    return subprocess.Popen([sys.executable, str(stt_path)], env=env)

def start_web_server():
    """Django 웹 서버 실행: python manage.py runserver 127.0.0.1:8000"""
    manage_py = ROOT / "manage.py"
    print(f"🌐 웹 서버 실행: {manage_py}")
    return subprocess.Popen([sys.executable, str(manage_py), "runserver", "127.0.0.1:8000"])

if __name__ == "__main__":
    print("🚀 두 서버를 동시에 실행합니다.")
    # 두 프로세스를 비동기로 시작
    stt_proc = start_stt_server()
    web_proc = start_web_server()

    try:
        # 두 프로세스가 모두 종료될 때까지 대기
        stt_proc.wait()
        web_proc.wait()
    except KeyboardInterrupt:
        # Ctrl+C로 중지하면 두 프로세스를 모두 종료
        print("\n🛑 종료 신호 감지 → 서버 종료 중...")
        stt_proc.terminate()
        web_proc.terminate()
