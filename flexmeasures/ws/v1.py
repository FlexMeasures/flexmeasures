import logging
from flexmeasures.ws import sock
from flask import current_app
from flexmeasures import Sensor
from sqlalchemy import select, func
import json
logger = logging.Logger(__name__)


@sock.route("/v1")
def header_test(ws):
    # Get all headers
    all_headers = {k[5:].lower().replace("_", "-"): v for k, v in ws.environ.items() if k.startswith("HTTP_")}

    # Get specific header if needed
    custom_header = ws.environ.get("HTTP_X_CUSTOM_HEADER")
    # show the type of ws
    logger.info(f"Type of ws: {type(ws)}")
    logger.info(f"All headers: {all_headers}")
    logger.info(f"Custom header: {custom_header}")

    # Send initial message with metadata
    ws.send(json.dumps({"type": "metadata", "headers": {"X-Server-Header": "ServerValue"}}))

    while True:
        data = ws.receive()
        logger.error("v1>" + data)
        if data == "close":
            break
        sensors = current_app.db.session.execute(select(func.count(Sensor.id))).scalar()
        ws.send(str(sensors))
