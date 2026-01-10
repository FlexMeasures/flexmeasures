import threading
import time

import pytest
import pytest_asyncio
import websockets
from werkzeug.serving import make_server


@pytest.fixture(scope="module")
def server(app):
    """Run Flask app with Sock in a thread for testing WebSocket"""
    srv = make_server("127.0.0.1", 5005, app)
    thread = threading.Thread(target=srv.serve_forever)
    thread.start()
    time.sleep(0.1)  # wait for server to start
    yield "ws://127.0.0.1:5005"
    srv.shutdown()
    thread.join()


@pytest_asyncio.fixture
async def connect_to_ws(server):
    """Yield a callable to connect to a given WS endpoint by name."""

    async def connect(endpoint_name):
        url = f"{server}/{endpoint_name}"
        conn = await websockets.connect(url)
        return conn

    yield connect
