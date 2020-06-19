from typing import List, Optional, Tuple, Union
import requests
from random import random
from datetime import datetime, timedelta

from numpy import sin, tile
from isodate import duration_isoformat, datetime_isoformat

from bvp.api.v1.tests.utils import message_for_post_meter_data
from bvp.api.v1_1.tests.utils import message_for_post_price_data


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


def get_auth_token(host: str, email: str, password: str) -> str:
    response = requests.post(
        "%s/api/requestAuthToken" % host, json={"email": email, "password": password},
    )
    response_json = response.json()
    if "auth_token" in response_json:
        return response_json["auth_token"]
    print(response_json)


def get_connections(
    host: str, latest_version: str, auth_token: str, include_names: bool = False
) -> Union[List[str], Tuple[List[str], List[str]]]:
    response = requests.get(
        "%s/api/%s/getConnection" % (host, latest_version),
        headers={"Authorization": auth_token},
    )
    if include_names:
        return response.json()["connections"], response.json()["names"]
    return response.json()["connections"]


def set_scheme_and_naming_authority(host: str) -> str:
    if host == "http://localhost:5000":
        return "ea1.2018-06.localhost:5000"
    elif host == "https://demo.a1-bvp.com":
        return "ea1.2018-06.com.a1-bvp.demo"
    elif host == "https://play.a1-bvp.com":
        return "ea1.2018-06.com.a1-bvp.play"
    elif host == "https://staging.a1-bvp.com":
        return "ea1.2018-06.com.a1-bvp.staging"
    else:
        raise ("Set market entity address for host %s." % host)


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


def post_weather_data(
    host: str, latest_version: str, auth_token: str, start: datetime, num_days: int
):
    lat = 33.4843866
    lng = 126
    values = [random() * 600 * (1 + sin(x / 15)) for x in range(96 * num_days)]
    message = {
        "type": "PostWeatherDataRequest",
        "sensor": "%s:%s:%s:%s"
        % (set_scheme_and_naming_authority(host), "radiation", lat, lng),
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


def get_prices(
    host: str, latest_version: str, auth_token: str, market_name: str,
):
    message = {
        "type": "GetPriceDataRequest",
        "market": f"{set_scheme_and_naming_authority(host)}:{market_name}",
    }
    response = requests.get(
        "%s/api/%s/getPriceData" % (host, latest_version),
        headers={"Authorization": auth_token},
        params=message,
    )
    if response.status_code != 200:
        print(response.content)
        print(response.json())
    return response


def post_soc_with_target(
    host: str,
    latest_version: str,
    auth_token: str,
    owner_id: int,
    asset_id: int,
    udi_event_id: int,
    soc_datetime: datetime,
    soc_value: float,
    target_datetime: datetime,
    target_value: float,
    unit: str = "MWh",
):
    message = {
        "type": "PostUdiEventRequest",
        "unit": unit,
        "event": f"{set_scheme_and_naming_authority(host)}:{owner_id}:{asset_id}:{udi_event_id}:soc-with-targets",
        "datetime": datetime_isoformat(soc_datetime),
        "value": soc_value,
        "targets": [
            {"value": target_value, "datetime": datetime_isoformat(target_datetime)}
        ],
    }
    response = requests.post(
        "%s/api/%s/postUdiEvent" % (host, latest_version),
        headers={"Authorization": auth_token},
        json=message,
    )
    if response.status_code != 200:
        print(response.json())


def get_device_message(
    host: str,
    latest_version: str,
    auth_token: str,
    owner_id: int,
    asset_id: int,
    udi_event_id: int,
    duration: Optional[timedelta] = None,
):
    message = {
        "type": "GetDeviceMessageRequest",
        "event": f"{set_scheme_and_naming_authority(host)}:{owner_id}:{asset_id}:{udi_event_id}:soc-with-targets",
    }
    if duration is not None:
        message.update({"duration": duration_isoformat(duration)})
    response = requests.get(
        "%s/api/%s/getDeviceMessage" % (host, latest_version),
        headers={"Authorization": auth_token},
        params=message,
    )
    if response.status_code != 200:
        print(response.content)
        print(response.json())
    return response
