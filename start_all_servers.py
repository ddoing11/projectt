import subprocess
import sys
import os
import multiprocessing

def start_video_detection():
    os.system("python video_detection.py")

def start_websocket_server():
    os.system("python websocket_server.py")

def start_web_server():
    # 현재 venv 경로 가져오기
    venv_python = os.path.join(os.getcwd(), 'venv', 'Scripts', 'python.exe')
    manage_py_path = os.path.join(os.getcwd(), 'manage.py')
    os.system(f'"{venv_python}" "{manage_py_path}" runserver 127.0.0.1:8000')

if __name__ == "__main__":
    print("🚀 모든 서버 실행 시작")
    multiprocessing.Process(target=start_video_detection).start()
    multiprocessing.Process(target=start_websocket_server).start()
    multiprocessing.Process(target=start_web_server).start()

    print("✅ 모든 서버가 실행되었습니다.")
    print("👀 서버 상태 모니터링 중... Ctrl+C로 종료하세요.")

    while True:
        pass
