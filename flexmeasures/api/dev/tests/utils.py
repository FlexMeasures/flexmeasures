def make_sensor_data_request(num_values: int = 6, duration: str = "PT1H") -> dict:
    return {
        "type": "PostSensorDataRequest",
        "sensor": "ea1.2021-01.io.flexmeasures:fm1.1",
        "values": num_values * [-11.28],
        "start": "2021-06-07T00:00:00+02:00",
        "duration": duration,
        "unit": "m³/h",
    }
