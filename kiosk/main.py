#!/usr/bin/env python3
"""
음성 인식 WebSocket 서버 메인 실행 파일
모듈화된 서버를 실행합니다.
"""

from kiosk.websocket_server import run_server

if __name__ == "__main__":
    print("🚀 음성 인식 WebSocket 서버를 시작합니다...")
    run_server()