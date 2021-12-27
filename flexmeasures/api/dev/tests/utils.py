from flexmeasures.data.models.time_series import Sensor


def make_sensor_data_request_for_gas_sensor(
    num_values: int = 6, duration: str = "PT1H", unit: str = "m³"
) -> dict:
    """Creates request to post sensor data for a gas sensor.
    This particular gas sensor measures units of m³/h with a 10-minute resolution.
    """
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    message: dict = {
        "type": "PostSensorDataRequest",
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "values": num_values * [-11.28],
        "start": "2021-06-07T00:00:00+02:00",
        "duration": duration,
        "unit": unit,
    }
    if num_values == 1:
        # flatten [<float>] to <float>
        message["values"] = message["values"][0]
    return message
