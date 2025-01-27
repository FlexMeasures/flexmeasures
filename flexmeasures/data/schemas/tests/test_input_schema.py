import inspect

from flexmeasures import Sensor
from flexmeasures.data.schemas.io import Input


def test_input_schema():
    """Input schema must describe all keyword arguments of the Sensor.search_beliefs method."""
    arg_names = inspect.getfullargspec(Sensor.search_beliefs).args
    field_names = Input._declared_fields.keys()

    # These arguments may have been mapped to a different field name (state a reason)
    mapped_arg_names = {
        "self": "sensor",  # mapped in Sensor.search_beliefs but not in TimedBelief.search
        "beliefs_before": "belief_time",  # todo: actually named 'prior' in the API, so this needs consolidating, preferably in the schema
    }

    # These arguments are not mapped to a field at all (state a reason)
    excluded_arg_names = [
        "as_json",  # used in Sensor.search_beliefs but not in TimedBelief.search
    ]

    arg_names_without_associated_fields = [
        arg_name
        for arg_name in arg_names
        if mapped_arg_names.get(arg_name, arg_name) not in field_names
        and arg_name not in excluded_arg_names
    ]
    if arg_names_without_associated_fields:
        raise NotImplementedError(
            f"Some search arguments have no associated field defined. Define a field for, or exclude from this test, the following arguments: {arg_names_without_associated_fields}",
        )
