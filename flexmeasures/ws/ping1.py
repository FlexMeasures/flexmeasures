import logging
from flexmeasures.ws import sock
from flask import current_app
from flexmeasures import Sensor
from sqlalchemy import select

logger = logging.Logger(__name__)


@sock.route("/ping1")
def echo1(ws):
    while True:
        with current_app.app_context():
            data = ws.receive()

            if data == "close":
                break

            sensors = current_app.db.session.execute(
                select(Sensor).where(Sensor.id == 1)
            ).scalar()

            ws.send(str(sensors.__dict__))
