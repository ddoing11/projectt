# start_all_servers.py 또는 start_servers.py
import multiprocessing
import os
import subprocess
import sys

def start_web_server():
    subprocess.run([sys.executable, "manage.py", "runserver", "127.0.0.1:8000"])

def start_stt_server():
    env = os.environ.copy()
    env.setdefault("PORT", "8002")  # STT 서버 포트
    subprocess.run([sys.executable, "kiosk/stt_ws_server.py"], env=env)

def start_message_router():
    env = os.environ.copy()
    env.setdefault("PORT", "8003")  # 메시지 라우터가 사용할 포트
    subprocess.run([sys.executable, "-m", "kiosk.websocket_server"], env=env)



if __name__ == "__main__":
    print("🚀 Django, STT, 메시지 라우터 서버 실행…")
    processes = [
        multiprocessing.Process(target=start_web_server),
        multiprocessing.Process(target=start_stt_server),
        multiprocessing.Process(target=start_message_router),
    ]
    for p in processes:
        p.start()
    for p in processes:
        p.join()
