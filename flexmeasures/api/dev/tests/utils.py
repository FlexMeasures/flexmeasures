from flexmeasures.data.models.time_series import Sensor


def make_sensor_data_request(num_values: int = 6, duration: str = "PT1H") -> dict:
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    message: dict = {
        "type": "PostSensorDataRequest",
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "values": num_values * [-11.28],
        "start": "2021-06-07T00:00:00+02:00",
        "duration": duration,
        "unit": "m³/h",
    }
    if num_values == 1:
        # flatten [<float>] to <float>
        message["values"] = message["values"][0]
    return message


def get_asset_post_data(account_id: int = 1, asset_type_id: int = 1) -> dict:
    post_data = {
        "name": "Test battery 2",
        "latitude": 30.1,
        "longitude": 100.42,
        "generic_asset_type_id": asset_type_id,
        "account_id": account_id,
    }
    return post_data
