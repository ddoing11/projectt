import asyncio
import websockets
import os
import sys
from websockets.exceptions import ConnectionClosedError

# Django 설정
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.aptitude.settings")
import django
django.setup()

from .simplified_message_router import SimplifiedMessageRouter


class WebSocketServer:
    def __init__(self):
        self.message_router = SimplifiedMessageRouter()

    async def echo(self, websocket):
        """WebSocket 연결 처리"""
        state = await self.message_router.handle_connection(websocket)
        
        try:
            while True:
                if state.get("finalized"):
                    await asyncio.sleep(1)
                    continue

                message = await websocket.recv()
                await self.message_router.process_message(websocket, message)

        except websockets.ConnectionClosed:
            print("❌ 클라이언트 연결 종료")
        except Exception as e:
            print(f"❌ 연결 처리 중 오류: {e}")
        finally:
            await self.message_router.cleanup_connection(websocket)

    async def start_server(self, host="0.0.0.0", port=None):
        """서버 시작"""
        if port is None:
            port = int(os.environ.get("PORT", 8002))
        
        async with websockets.serve(self.echo, host, port):
            print(f"✅ WebSocket 서버가 {port}번 포트에서 실행 중")
            await asyncio.Future()  # 서버를 계속 실행


def run_server():
    """서버 실행 함수"""
    server = WebSocketServer()
    asyncio.run(server.start_server())


if __name__ == "__main__":
    run_server()