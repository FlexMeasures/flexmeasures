from flexmeasures.data.models.time_series import Sensor


def make_sensor_data_request(num_values: int = 6, duration: str = "PT1H") -> dict:
    sensor = Sensor.query.filter(Sensor.name == "some gas sensor").one_or_none()
    return {
        "type": "PostSensorDataRequest",
        "sensor": f"ea1.2021-01.io.flexmeasures:fm1.{sensor.id}",
        "values": num_values * [-11.28],
        "start": "2021-06-07T00:00:00+02:00",
        "duration": duration,
        "unit": "m³/h",
    }
