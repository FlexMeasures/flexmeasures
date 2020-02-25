from typing import List
import requests
from random import random
from datetime import datetime, timedelta
import time
import os

from numpy import sin, tile
from isodate import duration_isoformat, datetime_isoformat

from bvp.api.v1.tests.utils import message_for_post_meter_data
from bvp.api.v1_1.tests.utils import message_for_post_price_data


def get_PA_token() -> str:
    """Retrieve Python Anywhere token from environment (if set as env variable) or from dev config."""
    token = os.environ.get("API_TOKEN")
    if token is None:
        from bvp.development_config import PA_API_TOKEN as token
    return token


def get_cpu_seconds(username: str, auth_token: str) -> (float, int):
    response = requests.get(
        f"https://www.pythonanywhere.com/api/v0/user/{username}/cpu/",
        headers={"Authorization": f"Token {auth_token}"},
    )
    return (
        response.json()["daily_cpu_total_usage_seconds"],
        response.json()["daily_cpu_limit_seconds"],
    )


def check_version(host: str) -> str:
    response = requests.get("%s/api/" % host)
    latest_version = response.json()["versions"][-1]
    print("Latest API version on host %s is %s." % (host, latest_version))
    return latest_version


def check_services(host: str, latest_version: str) -> List[str]:
    response = requests.get("%s/api/%s/getService" % (host, latest_version))
    services = [service["name"] for service in response.json()["services"]]
    for service in (
        "getConnection",
        "postWeatherData",
        "postPriceData",
        "postMeterData",
        "getPrognosis",
        "postUdiEvent",
        "getDeviceMessage",
    ):
        assert service in services
    return services


def get_auth_token(host: str) -> str:
    response = requests.post(
        "%s/api/requestAuthToken" % host,
        json={"email": "solar@seita.nl", "password": "solar"},
    )
    return response.json()["auth_token"]


def get_connections(host: str, latest_version: str, auth_token: str) -> List[str]:
    response = requests.get(
        "%s/api/%s/getConnection" % (host, latest_version),
        headers={"Authorization": auth_token},
    )
    return response.json()["connections"]


def set_scheme_and_naming_authority(host: str) -> str:
    if host == "http://localhost:5000":
        return "ea1.2018-06.localhost:5000:"
    elif host == "https://play.a1-bvp.com":
        return "ea1.2018-06.com.a1-bvp.play:"
    elif host == "https://staging.a1-bvp.com":
        return "ea1.2018-06.com.a1-bvp.staging:"
    else:
        raise ("Set market entity address for host %s." % host)


def post_meter_data(
    host: str,
    latest_version: str,
    auth_token: str,
    start: datetime,
    batch_size: int,
    connection: str,
):
    message = message_for_post_meter_data(
        tile_n=round(batch_size / 6), production=True, single_connection=True
    )  # Original message is just 6 values (1.5 hours)
    message["start"] = datetime_isoformat(start)
    message["connection"] = connection
    if batch_size < 6:
        import random

        message["values"] = random.sample(
            range(0, -300, -1), batch_size
        )  # production is negative
        message["duration"] = duration_isoformat(timedelta(minutes=15 * batch_size))
    response = requests.post(
        "%s/api/%s/postMeterData" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    assert response.status_code == 200


def post_price_forecasts(
    host: str, latest_version: str, auth_token: str, start: datetime, num_days: int
):
    market_ea = "%s:%s" % (set_scheme_and_naming_authority(host), "kpx_da")
    message = message_for_post_price_data(tile_n=num_days)
    message["start"] = datetime_isoformat(start)
    message["market"] = market_ea
    message["unit"] = "KRW/kWh"
    response = requests.post(
        "%s/api/%s/postPriceData" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    assert response.status_code == 200


def post_weather_forecasts(
    host: str, latest_version: str, auth_token: str, start: datetime, num_days: int
):
    lat = 33.4843866
    lng = 126.477859
    values = [round(random() * 600 * (1 + sin(x / 15))) for x in range(96 * num_days)]
    message = {
        "type": "PostWeatherDataRequest",
        "sensor": "%s:%s:%s:%s"
        % (set_scheme_and_naming_authority(host), "radiation", lat, lng),
        "values": tile(values, 1).tolist(),
        "start": datetime_isoformat(start),
        "duration": duration_isoformat(timedelta(hours=24 * num_days)),
        "horizon": "R/PT48H",
        "unit": "kW/m²",
    }
    response = requests.post(
        "%s/api/%s/postWeatherData" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    assert response.status_code == 200


class Timer(object):
    """Usage example:

    >>> with Timer("Calling max function"):
    >>>     a = max(range(10**6))
    <<<
    [Calling max function] Starting (at Friday, October 18, 2019 16:16:18) ...
    [Calling max function] Elapsed: 35 ms
    """

    def __init__(self, name=None, filename=None):
        self.name = name
        self.filename = filename

    def __enter__(self):
        self.tstart = time.time()
        print(
            "[%s] Starting (at %s) ..."
            % (
                self.name,
                datetime.fromtimestamp(self.tstart).strftime("%A, %B %d, %Y %H:%M:%S"),
            )
        )

    def __exit__(self, type, value, traceback):
        duration = time.time() - self.tstart
        if duration > 1:
            message = "Elapsed: %.2f seconds" % duration
        else:
            message = "Elapsed: %.0f ms" % (duration * 1000)
        if self.name:
            message = "[%s] " % self.name + message
        print(message)
        if self.filename:
            with open(self.filename, "a") as file:
                print(str(datetime.now()) + ": ", message, file=file)
