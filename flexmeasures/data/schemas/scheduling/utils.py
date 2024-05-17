from __future__ import annotations

from flexmeasures import Sensor


def find_sensors(data, parent_key='', path='') -> list[tuple[Sensor, str]]:
    """Recursively find all sensors in a nested dictionary or list along with the fields referring to them."""
    sensors = []

    if isinstance(data, dict):
        for key, value in data.items():
            new_parent_key = f"{parent_key}.{key}" if parent_key else key
            new_path = f"{path}.{key}" if path else key
            if isinstance(value, Sensor):
                sensors.append((value, f"{new_parent_key}{path}"))
            else:
                sensors.extend(find_sensors(value, new_parent_key, new_path))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            new_parent_key = f"{parent_key}[{index}]"
            new_path = f"{path}[{index}]"
            sensors.extend(find_sensors(item, new_parent_key, new_path))

    return sensors
