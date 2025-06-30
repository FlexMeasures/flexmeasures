import logging
from flexmeasures.ws import sock
from flask import current_app
from flexmeasures import Sensor
from sqlalchemy import select, func
import uuid
import json
logger = logging.getLogger(__name__)


@sock.route("/ping1")
async def echo1(ws):
    headers = ws.environ  # Access all headers from the connection
    client_id = str(uuid.uuid4())
    
    logger.info("-----------------------------------------")
    logger.info(f"Received headers: {headers}")
    logger.info("-----------------------------------------")
    logger.info(f"Type of ws: {type(ws)}")
    logger.info(f"Client ID: {client_id}")
    await ws.send(json.dumps({"type": "metadata", "headers": {"X-Server-Header": "ServerValue"}}))
    while True:
        data = await ws.receive()
        logger.error("ping1>" + data)
        if data == "close":
            break
        # sensors = current_app.db.session.execute(select(func.count(Sensor.id))).scalar()
        await ws.send(data )
