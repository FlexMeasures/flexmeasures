from typing import List, Optional
import requests
from random import random
from datetime import datetime, timedelta

from numpy import sin, tile
from isodate import duration_isoformat, datetime_isoformat

from flexmeasures.utils.entity_address_utils import build_ea_scheme_and_naming_authority
from flexmeasures.api.v1.tests.utils import message_for_post_meter_data
from flexmeasures.api.v1_1.tests.utils import message_for_post_price_data


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


def post_meter_data(
    host: str,
    latest_version: str,
    auth_token: str,
    start: datetime,
    num_days: int,
    connection: str,
):
    message = message_for_post_meter_data(
        tile_n=num_days * 16, production=True
    )  # Original message is just 1.5 hours
    message["start"] = datetime_isoformat(start)
    message["connection"] = connection
    response = requests.post(
        "%s/api/%s/postMeterData" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    assert response.status_code == 200


def post_price_forecasts(
    host: str,
    latest_version: str,
    auth_token: str,
    start: datetime,
    num_days: int,
    host_auth_start_month: Optional[str] = None,
):
    market_ea = "%s:%s" % (
        build_ea_scheme_and_naming_authority(host, host_auth_start_month),
        "kpx_da",
    )
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


def post_weather_data(
    host: str,
    latest_version: str,
    auth_token: str,
    start: datetime,
    num_days: int,
    host_auth_start_month: Optional[str] = None,
):
    lat = 33.4843866
    lng = 126
    values = [random() * 600 * (1 + sin(x / 15)) for x in range(96 * num_days)]
    message = {
        "type": "PostWeatherDataRequest",
        "sensor": "%s:%s:%s:%s"
        % (
            build_ea_scheme_and_naming_authority(host, host_auth_start_month),
            "radiation",
            lat,
            lng,
        ),
        "values": tile(values, 1).tolist(),
        "start": datetime_isoformat(start),
        "duration": duration_isoformat(timedelta(hours=24 * num_days)),
        "horizon": "R/PT0H",
        "unit": "kW/m²",
    }
    response = requests.post(
        "%s/api/%s/postWeatherData" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    assert response.status_code == 200
