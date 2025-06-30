from simple_websocket import Client, ConnectionClosed  # type: ignore
import json
import sys

import asyncio
import websockets


async def main():
    uri = "ws://127.0.0.1:5000/ping1"
    headers = {
        "X-Custom-Header": "SomeValue",
        "Authorization": "Bearer YourToken",
    }

    async with websockets.connect(uri, extra_headers=headers) as ws:
        while True:
            data = input("> ")
            await ws.send(data)
            response = await ws.recv()
            print(f"< {response}")


if __name__ == "__main__":
    asyncio.run(main())

# def main():
#     headers = {
#         "X-Custom-Header": "SomeValue",
#         # 'Authorization': 'Bearer YourToken',
#     }
#     ws = Client.connect("ws://127.0.0.1:5000/ping1", headers=headers)
#     try:
#         print("Connected to the WebSocket server!")
#
#         # Get initial metadata message
#         initial_msg = json.loads(ws.receive())
#         print(initial_msg)
#         if initial_msg.get("type") != "metadata":
#             print("ERROR: Server metadata not received!")
#             ws.close()
#             sys.exit(1)
#
#         server_header = initial_msg.get("headers", {}).get("X-Server-Header")
#         if not server_header:
#             print("ERROR: Server header not found in metadata!")
#             ws.close()
#             sys.exit(1)
#         print(f"Server header received: {server_header}")
#
#         while True:
#             data = input("> ")
#             ws.send(data)
#             data = ws.receive()
#             print(f"< {data}")
#
#     except (KeyboardInterrupt, EOFError, ConnectionClosed) as e:
#         print(f"Connection closed: {e}")
#         ws.close()


if __name__ == "__main__":
    main()
