import logging
from flexmeasures.ws import sock
from flask import current_app
from flexmeasures import Sensor
from sqlalchemy import select, func

logger = logging.getLogger(__name__)


@sock.route("/ping1")
def echo1(ws):
    headers = ws.environ  # Access all headers from the connection
    logger.info("-----------------------------------------")
    logger.info(f"Received headers: {headers}")
    logger.info("-----------------------------------------")

    while True:
        data = ws.receive()
        logger.error("ping1>" + data)
        if data == "close":
            break
        sensors = current_app.db.session.execute(select(func.count(Sensor.id))).scalar()
        ws.send(str(sensors))
