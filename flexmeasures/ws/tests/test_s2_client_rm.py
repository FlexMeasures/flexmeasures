import pytest

import logging
import websockets

logger = logging.getLogger("s2python")
SERVER_URL = "ws://127.0.0.1:5000"


@pytest.mark.asyncio
async def test_ping2_echo(connect_to_ws):

    # Connect to WS endpoint
    ws = await connect_to_ws("ping2")

    # Send a message
    await ws.send("hello")
    resp = await ws.recv()
    assert resp == "hello", "echo should return the same message"

    # Trigger server-side close
    await ws.send("close")
    with pytest.raises(websockets.exceptions.ConnectionClosedOK):
        await ws.recv(), "expected that, after sending 'close', server breaks loop; connection closes"
