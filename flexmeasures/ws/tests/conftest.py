import threading
import time

import pytest
import pytest_asyncio
import websockets


@pytest.fixture(scope="module")
def server(app):
    """Run Flask app with Sock in a thread for testing WebSocket"""
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", 5005, app)
    thread = threading.Thread(target=srv.serve_forever)
    thread.start()
    time.sleep(0.1)  # wait for server to start
    yield "ws://127.0.0.1:5005/ping2"
    srv.shutdown()
    thread.join()


@pytest_asyncio.fixture
async def ws(server):
    """Provide an already connected WebSocket client to tests"""
    async with websockets.connect(server) as websocket:
        yield websocket
