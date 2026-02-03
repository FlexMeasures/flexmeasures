import logging
from flexmeasures.ws import sock

logger = logging.Logger(__name__)


@sock.route("/ping2")
def echo2(ws):
    while True:
        data = ws.receive()
        logger.error("ping2>" + data)
        if data == "close":
            break
        ws.send(data)
