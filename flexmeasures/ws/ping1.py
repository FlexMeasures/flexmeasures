import logging
from flexmeasures.ws import sock

logger = logging.Logger(__name__)


@sock.route("/ping1")
def echo1(ws):
    while True:
        data = ws.receive()
        logger.error("ping1>" + data)
        if data == "close":
            break
        ws.send(data)
