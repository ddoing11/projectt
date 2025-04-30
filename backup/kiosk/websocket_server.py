import asyncio
import websockets

connected_clients = set()

async def echo(websocket):  # ✅ path 제거
    print("🔗 클라이언트 연결됨")
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            message = message.strip()
            print(f"📨 받은 메시지: {message}")
            if message == "start_order":
                print("🗣️ '음성으로 주문하시겠습니까?' 전송 중")
                await websocket.send("음성으로 주문하시겠습니까?")
            elif "네" in message:
                await websocket.send("음성 주문을 시작합니다. 원하시는 메뉴가 있으신가요?")
            elif "아니" in message:
                await websocket.send("음성 인식을 종료합니다. 일반 키오스크로 주문을 진행하세요.")
            else:
                await websocket.send("죄송합니다. 다시 말씀해 주세요.")
    except websockets.ConnectionClosed:
        print("❌ 클라이언트 연결 종료")
    finally:
        connected_clients.remove(websocket)

async def main():
    async with websockets.serve(echo, "localhost", 8002):
        print("✅ WebSocket 서버가 8002 포트에서 실행 중")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
