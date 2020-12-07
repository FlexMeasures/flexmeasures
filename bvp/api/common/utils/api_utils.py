from typing import List, Union, Sequence, Optional
import copy
import re
from datetime import timedelta
from json import loads as parse_json, JSONDecodeError

from flask import current_app
from inflection import pluralize
from numpy import array

from bvp.data import db
from bvp.data.models.assets import Asset
from bvp.data.models.markets import Market
from bvp.data.models.data_sources import DataSource
from bvp.data.models.weather import WeatherSensor
from bvp.data.models.user import User
from bvp.api.common.responses import unrecognized_sensor


def list_access(service_listing, service_name):
    """
    For a given USEF service name (API endpoint) in a service listing,
    return the list of USEF roles that are allowed to access the service.
    """
    return next(
        service["access"]
        for service in service_listing["services"]
        if service["name"] == service_name
    )


def contains_empty_items(groups: List[List[str]]):
    """
    Return True if any of the items in the groups is empty.
    """
    for group in groups:
        for item in group:
            if item == "" or item is None:
                return True
    return False


def parse_as_list(
    connection: Union[Sequence[Union[str, float]], str, float], of_type: type = None
) -> Sequence[Union[str, float, None]]:
    """
    Return a list of connections (or values), even if it's just one connection (or value)
    """
    connections: Sequence[Union[str, float, None]] = []
    if not isinstance(connection, list):
        if of_type is None:
            connections = [connection]  # type: ignore
        else:
            try:
                connections = [of_type(connection)]
            except TypeError:
                connections = [None]
    else:  # key should have been plural
        if of_type is None:
            connections = connection
        else:
            try:
                connections = [of_type(c) for c in connection]
            except TypeError:
                connections = [None]
    return connections


def get_form_from_request(_request) -> Union[dict, None]:
    if _request.method == "GET":
        d = _request.args.to_dict(
            flat=False
        )  # From MultiDict, obtain all values with the same key as a list
        parsed_d = {}
        for k, v_list in d.items():
            parsed_v_list = []
            for v in v_list:
                try:
                    parsed_v = parse_json(v)
                except JSONDecodeError:
                    parsed_v = v
                if isinstance(parsed_v, list):
                    parsed_v_list.extend(parsed_v)
                else:
                    parsed_v_list.append(v)
            if len(parsed_v_list) == 1:  # Flatten single-value lists
                parsed_d[k] = parsed_v_list[0]
            else:
                parsed_d[k] = parsed_v_list
        return parsed_d
    elif _request.method == "POST":
        return _request.get_json(force=True)
    else:
        return None


def append_doc_of(fun):
    def decorator(f):
        if f.__doc__:
            f.__doc__ += fun.__doc__
        else:
            f.__doc__ = fun.__doc__
        return f

    return decorator


def upsample_values(
    value_groups: Union[List[List[float]], List[float]],
    from_resolution: timedelta,
    to_resolution: timedelta,
) -> Union[List[List[float]], List[float]]:
    """Upsample the values (in value groups) to a smaller resolution.
    from_resolution has to be a multiple of to_resolution"""
    if from_resolution % to_resolution == timedelta(hours=0):
        n = from_resolution // to_resolution
        if isinstance(value_groups[0], list):
            value_groups = [
                list(array(value_group).repeat(n)) for value_group in value_groups
            ]
        else:
            value_groups = list(array(value_groups).repeat(n))
    return value_groups


def groups_to_dict(
    connection_groups: List[str],
    value_groups: List[List[str]],
    generic_asset_type_name: str,
    plural_name: str = None,
    groups_name="groups",
) -> dict:
    """Put the connections and values in a dictionary and simplify if groups have identical values and/or if there is
    only one group.

    Examples:

        >> connection_groups = [[1]]
        >> value_groups = [[300, 300, 300]]
        >> response_dict = groups_to_dict(connection_groups, value_groups, "connection")
        >> print(response_dict)
        <<  {
                "connection": 1,
                "values": [300, 300, 300]
            }

        >> connection_groups = [[1], [2]]
        >> value_groups = [[300, 300, 300], [300, 300, 300]]
        >> response_dict = groups_to_dict(connection_groups, value_groups, "connection")
        >> print(response_dict)
        <<  {
                "connections": [1, 2],
                "values": [300, 300, 300]
            }

        >> connection_groups = [[1], [2]]
        >> value_groups = [[300, 300, 300], [400, 400, 400]]
        >> response_dict = groups_to_dict(connection_groups, value_groups, "connection")
        >> print(response_dict)
        <<  {
                "groups": [
                    {
                        "connection": 1,
                        "values": [300, 300, 300]
                    },
                    {
                        "connection": 2,
                        "values": [400, 400, 400]
                    }
                ]
            }
    """

    if plural_name is None:
        plural_name = pluralize(generic_asset_type_name)

    # Simplify groups that have identical values
    value_groups, connection_groups = unique_ever_seen(value_groups, connection_groups)

    # Simplify if there is only one group
    if len(value_groups) == len(connection_groups) == 1:
        if len(connection_groups[0]) == 1:
            return {
                generic_asset_type_name: connection_groups[0][0],
                "values": value_groups[0],
            }
        else:
            return {plural_name: connection_groups[0], "values": value_groups[0]}
    else:
        d: dict = {groups_name: []}
        for connection_group, value_group in zip(connection_groups, value_groups):
            if len(connection_group) == 1:
                d[groups_name].append(
                    {
                        generic_asset_type_name: connection_group[0],
                        "values": value_group,
                    }
                )
            else:
                d[groups_name].append(
                    {plural_name: connection_group, "values": value_group}
                )
        return d


def unique_ever_seen(iterable: Sequence, selector: Sequence):
    """
    Return unique iterable elements with corresponding lists of selector elements, preserving order.

    >>> a, b = unique_ever_seen([[10, 20], [10, 20], [20, 40]], [1, 2, 3])
    >>> print(a)
    [[10, 20], [20, 40]]
    >>> print(b)
    [[1, 2], 3]
    """
    u = []
    s = []
    for iterable_element, selector_element in zip(iterable, selector):
        if iterable_element not in u:
            u.append(iterable_element)
            s.append(selector_element)
        else:
            us = s[u.index(iterable_element)]
            if not isinstance(us, list):
                us = [us]
            us.append(selector_element)
            s[u.index(iterable_element)] = us
    return u, s


def message_replace_name_with_ea(message_with_connections_as_asset_names: dict) -> dict:
    """For each connection in the message specified by a name, replace that name with the correct entity address."""
    message_with_connections_as_eas = copy.deepcopy(
        message_with_connections_as_asset_names
    )
    if "connection" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connection"] = asset_replace_name_with_id(
            parse_as_list(  # type:ignore
                message_with_connections_as_eas["connection"], of_type=str
            )
        )
    elif "connections" in message_with_connections_as_asset_names:
        message_with_connections_as_eas["connections"] = asset_replace_name_with_id(
            parse_as_list(  # type:ignore
                message_with_connections_as_eas["connections"], of_type=str
            )
        )
    elif "groups" in message_with_connections_as_asset_names:
        for i, group in enumerate(message_with_connections_as_asset_names["groups"]):
            if "connection" in group:
                message_with_connections_as_eas["groups"][i][
                    "connection"
                ] = asset_replace_name_with_id(
                    parse_as_list(group["connection"], of_type=str)  # type:ignore
                )
            elif "connections" in group:
                message_with_connections_as_eas["groups"][i][
                    "connections"
                ] = asset_replace_name_with_id(
                    parse_as_list(group["connections"], of_type=str)  # type:ignore
                )
    return message_with_connections_as_eas


def asset_replace_name_with_id(connections_as_name: List[str]) -> List[str]:
    """Look up the owner and id given the asset name and construct a type 1 USEF entity address."""
    connections_as_ea = []
    for asset_name in connections_as_name:
        asset = Asset.query.filter(Asset.name == asset_name).one_or_none()
        connections_as_ea.append(asset.entity_address)
    return connections_as_ea


def typed_regex_results(match, value_types) -> dict:
    return {
        k: v_type(v) if v is not None else v
        for k, v, v_type in zip_dic(match.groupdict(), value_types)
    }


def zip_dic(*dicts):
    for i in set(dicts[0]).intersection(*dicts[1:]):
        yield (i,) + tuple(d[i] for d in dicts)


def get_or_create_user_data_source(user: User) -> DataSource:
    data_source = DataSource.query.filter(DataSource.user == user).one_or_none()
    if not data_source:
        current_app.logger.info("SETTING UP USER AS NEW DATA SOURCE...")
        data_source = DataSource(user=user)
        db.session.add(data_source)
        db.session.flush()  # flush so that we can reference the new object in the current db session
    return data_source


def parse_entity_address(generic_asset_name: str, entity_type: str) -> Optional[dict]:
    """
    Parses a generic asset name into an info dict.
    The generic asset name must be a valid type 1 USEF entity address.
    That is, it must follow the EA1 addressing scheme recommended by USEF.

    For example:

        connection = ea1.2018-06.localhost:5000:40:30
        connection = ea1.2018-06.com.a1-bvp:<owner_id>:<asset_id>
        sensor = ea1.2018-06.com.a1-bvp:temperature:52:73.0
        sensor = ea1.2018-06.com.a1-bvp:<sensor_type>:<latitude>:<longitude>
        market = ea1.2018-06.com.a1-bvp:epex_da
        market = ea1.2018-06.com.a1-bvp:<market_name>
        event = ea1.2018-06.com.a1-bvp:5000:40:30:302:soc
        event = ea1.2018-06.com.a1-bvp:<owner_id>:<asset_id>:<event_id>:<event_type>

    Returns a dictionary with scheme, naming_authority and various other fields,
    depending on the entity type.
    Returns None if entity type is unkown.
    We recommend to `return invalid_domain()` in that case.
    """
    if entity_type == "connection":
        match = re.search(
            r"^"
            r"((?P<scheme>.+)\.)*"
            r"((?P<naming_authority>\d{4}-\d{2}\..+):(?=.+:))*"  # scheme, naming authority and owner id are optional
            r"((?P<owner_id>\d+):(?=.+:{0}))*"
            r"(?P<asset_id>\d+)"
            r"$",
            generic_asset_name,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "owner_id": int,
                "asset_id": int,
            }
            return typed_regex_results(match, value_types)
    elif entity_type == "sensor":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            r"(?P<naming_authority>\d{4}-\d{2}\..+)"
            r":"
            r"(?=[a-zA-Z])(?P<weather_sensor_type_name>[\w]+)"  # should start with at least one letter
            r":"
            r"(?P<latitude>\d+(\.\d+)?)"
            r":"
            r"(?P<longitude>\d+(\.\d+)?)"
            r"$",
            generic_asset_name,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "weather_sensor_type_name": str,
                "latitude": float,
                "longitude": float,
            }
            return typed_regex_results(match, value_types)
    elif entity_type == "market":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            r"(?P<naming_authority>\d{4}-\d{2}\..+)"
            r":"
            r"(?=[a-zA-Z])(?P<market_name>[\w]+)"  # should start with at least one letter
            r"$",
            generic_asset_name,
        )
        if match:
            value_types = {"scheme": str, "naming_authority": str, "market_name": str}
            return typed_regex_results(match, value_types)
    elif entity_type == "event":
        match = re.search(
            r"^"
            r"(?P<scheme>.+)"
            r"\."
            r"(?P<naming_authority>\d{4}-\d{2}\..+)"
            r":"
            r"(?P<owner_id>\d+)"
            r":"
            r"(?P<asset_id>\d+)"
            r":"
            r"(?P<event_id>\d+)"
            r":"
            r"(?P<event_type>.+)"
            r"$",
            generic_asset_name,
        )
        if match:
            value_types = {
                "scheme": str,
                "naming_authority": str,
                "owner_id": int,
                "asset_id": int,
                "event_id": int,
                "event_type": str,
            }
            return typed_regex_results(match, value_types)
    current_app.logger.warning(f"Entity type {entity_type} not recognized.")
    return None


def get_weather_sensor_by(
    weather_sensor_type_name: str, latitude: float = 0, longitude: float = 0
) -> WeatherSensor:
    """
    Search a weather sensor by type and location.
    Can create a weather sensor if needed (depends on API mode)
    and then inform the requesting user which one to use.
    """
    # Look for the WeatherSensor object
    weather_sensor = (
        WeatherSensor.query.filter(
            WeatherSensor.weather_sensor_type_name == weather_sensor_type_name
        )
        .filter(WeatherSensor.latitude == latitude)
        .filter(WeatherSensor.longitude == longitude)
        .one_or_none()
    )
    if weather_sensor is None:
        create_sensor_if_unknown = False
        if current_app.config.get("BVP_MODE", "") == "play":
            create_sensor_if_unknown = True

        # either create a new weather sensor and post to that
        if create_sensor_if_unknown:
            current_app.logger.info("CREATING NEW WEATHER SENSOR...")
            weather_sensor = WeatherSensor(
                name="Weather sensor for %s at latitude %s and longitude %s"
                % (weather_sensor_type_name, latitude, longitude),
                weather_sensor_type_name=weather_sensor_type_name,
                latitude=latitude,
                longitude=longitude,
            )
            db.session.add(weather_sensor)
            db.session.flush()  # flush so that we can reference the new object in the current db session

        # or query and return the nearest sensor and let the requesting user post to that one
        else:
            nearest_weather_sensor = WeatherSensor.query.order_by(
                WeatherSensor.great_circle_distance(
                    latitude=latitude, longitude=longitude
                ).asc()
            ).first()
            if nearest_weather_sensor is not None:
                return unrecognized_sensor(
                    nearest_weather_sensor.latitude,
                    nearest_weather_sensor.longitude,
                )
            else:
                return unrecognized_sensor()
    return weather_sensor


def get_generic_asset(asset_descriptor, entity_type):
    """
    Get a generic asset from form information
    # TODO: After refactoring, unify 3 generic_asset cases -> 1 sensor case
    """
    ea = parse_entity_address(asset_descriptor, entity_type=entity_type)
    if ea is None:
        return None
    if entity_type == "connection":
        return Asset.query.filter(Asset.id == ea["asset_id"]).one_or_none()
    elif entity_type == "market":
        return Market.query.filter(Market.name == ea["market_name"]).one_or_none()
    elif entity_type == "sensor":
        return get_weather_sensor_by(
            ea["weather_sensor_type_name"],
            ea["latitude"],
            ea["longitude"],
        )
    return None
