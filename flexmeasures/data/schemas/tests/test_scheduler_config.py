from flexmeasures.data.schemas.scheduling.config import (
    find_momentary_flex_config_fields,
    strip_momentary_flex_fields,
)


def test_a_moment_leaves_no_trace_whichever_shape_it_came_in():
    """However a momentary value was written, the configuration left behind is the same.

    A single moment may be given as one mapping or as a list of them,
    so keeping the field as a null or an empty list would make one spelling a different configuration than the other,
    and both different from leaving the field out.
    """
    as_a_list = [{"sensor": 1, "soc-targets": [{"datetime": "x", "value": 1}]}]
    as_a_mapping = [{"sensor": 1, "soc-targets": {"datetime": "x", "value": 1}}]
    left_out = [{"sensor": 1}]

    assert strip_momentary_flex_fields(as_a_list) == left_out
    assert strip_momentary_flex_fields(as_a_mapping) == left_out
    assert strip_momentary_flex_fields(left_out) == left_out


def test_stripping_keeps_what_holds_beyond_one_moment():
    """Sensor references and plain quantities survive, and so do the static entries of a mixed list."""
    flex_model = [
        {
            "sensor": 1,
            "power-capacity": "2 MW",
            "soc-at-start": "5 kWh",
            "soc-targets": [{"datetime": "x", "value": 1}, {"sensor": 9}],
        }
    ]
    assert strip_momentary_flex_fields(flex_model) == [
        {"sensor": 1, "power-capacity": "2 MW", "soc-targets": [{"sensor": 9}]}
    ]
    # An empty list was not emptied by stripping, so it stays as it was given.
    assert strip_momentary_flex_fields([{"soc-targets": []}]) == [{"soc-targets": []}]


def test_momentary_fields_are_reported_by_their_path():
    """The paths name the field at fault, which is what the CLI tells the user."""
    assert find_momentary_flex_config_fields(
        {
            "flex-model": [
                {"soc-at-start": "5 kWh", "soc-targets": [{"datetime": "x"}]},
            ],
            "flex-context": {"consumption-price": {"sensor": 3}},
        }
    ) == ["flex-model[0].soc-at-start", "flex-model[0].soc-targets[0]"]
