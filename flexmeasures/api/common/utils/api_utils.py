from __future__ import annotations

from timely_beliefs.beliefs.classes import BeliefsDataFrame
from typing import List, Sequence, Tuple, Union
from datetime import datetime, timedelta
from json import loads as parse_json, JSONDecodeError

from flask import current_app
from inflection import pluralize
from numpy import array
from psycopg2.errors import UniqueViolation
from rq.job import Job
from sqlalchemy.exc import IntegrityError
import timely_beliefs as tb

from flexmeasures.data import db
from flexmeasures.data.utils import save_to_db as modern_save_to_db
from flexmeasures.api.common.responses import (
    invalid_replacement,
    ResponseTuple,
    request_processed,
    already_received_and_successfully_processed,
)
from flexmeasures.utils.error_utils import error_handling_router


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
    connection: str | float | Sequence[str | float], of_type: type | None = None
) -> Sequence[str | float | None]:
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


# TODO: deprecate ― we should be using webargs to get data from a request, it's more descriptive and has error handling
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
    plural_name: str | None = None,
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


def enqueue_forecasting_jobs(
    forecasting_jobs: list[Job] | None = None,
):
    """Enqueue forecasting jobs.

    :param forecasting_jobs: list of forecasting Jobs for redis queues.
    """
    if forecasting_jobs is not None:
        [current_app.queues["forecasting"].enqueue_job(job) for job in forecasting_jobs]


def save_and_enqueue(
    data: Union[BeliefsDataFrame, List[BeliefsDataFrame]],
    forecasting_jobs: list[Job] | None = None,
    save_changed_beliefs_only: bool = True,
) -> ResponseTuple:

    # Attempt to save
    status = modern_save_to_db(
        data, save_changed_beliefs_only=save_changed_beliefs_only
    )
    db.session.commit()

    # Only enqueue forecasting jobs upon successfully saving new data
    if status[:7] == "success" and status != "success_but_nothing_new":
        enqueue_forecasting_jobs(forecasting_jobs)

    # Pick a response
    if status == "success":
        return request_processed()
    elif status in (
        "success_with_unchanged_beliefs_skipped",
        "success_but_nothing_new",
    ):
        return already_received_and_successfully_processed()
    return invalid_replacement()


def determine_belief_timing(
    event_values: list,
    start: datetime,
    resolution: timedelta,
    horizon: timedelta,
    prior: datetime,
    sensor: tb.Sensor,
) -> Tuple[List[datetime], List[timedelta]]:
    """Determine event starts from start, resolution and len(event_values),
    and belief horizons from horizon, prior, or both, taking into account
    the sensor's knowledge horizon function.

    In case both horizon and prior is set, we take the greatest belief horizon,
    which represents the earliest belief time.
    """
    event_starts = [start + j * resolution for j in range(len(event_values))]
    belief_horizons_from_horizon = None
    belief_horizons_from_prior = None
    if horizon is not None:
        belief_horizons_from_horizon = [horizon] * len(event_values)
        if prior is None:
            return event_starts, belief_horizons_from_horizon
    if prior is not None:
        belief_horizons_from_prior = [
            event_start - prior - sensor.knowledge_horizon(event_start)
            for event_start in event_starts
        ]
        if horizon is None:
            return event_starts, belief_horizons_from_prior
    if (
        belief_horizons_from_horizon is not None
        and belief_horizons_from_prior is not None
    ):
        belief_horizons = [
            max(a, b)
            for a, b in zip(belief_horizons_from_horizon, belief_horizons_from_prior)
        ]
        return event_starts, belief_horizons
    raise ValueError("Missing horizon or prior.")


def catch_timed_belief_replacements(error: IntegrityError):
    """Catch IntegrityErrors due to a UniqueViolation on the TimedBelief primary key.

    Return a more informative message.
    """
    if isinstance(error.orig, UniqueViolation) and "timed_belief_pkey" in str(
        error.orig
    ):
        # Some beliefs represented replacements, which was forbidden
        return invalid_replacement()

    # Forward to our generic error handler
    return error_handling_router(error)
