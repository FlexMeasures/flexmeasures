from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS
from flexmeasures.utils.flexmeasures_inflection import capitalize


def bar_chart(
    sensor: "Sensor",  # noqa F821
    **override_chart_specs: dict,
):
    unit = sensor.unit if sensor.unit else "a.u."
    event_value_field_definition = dict(
        title=f"{capitalize(sensor.sensor_type)} ({unit})",
        format=".3s",
        stack=None,
        **FIELD_DEFINITIONS["event_value"],
    )
    chart_specs = {
        "description": "A simple bar chart.",
        "title": capitalize(sensor.name),
        "mark": "bar",
        "encoding": {
            "x": FIELD_DEFINITIONS["event_start"],
            "x2": FIELD_DEFINITIONS["event_end"],
            "y": event_value_field_definition,
            "color": FIELD_DEFINITIONS["source"],
            "opacity": {"value": 0.7},
            "tooltip": [
                FIELD_DEFINITIONS["full_date"],
                event_value_field_definition,
                FIELD_DEFINITIONS["source"],
            ],
        },
        "transform": [
            {
                "calculate": f"datum.event_start + {sensor.event_resolution.total_seconds() * 1000}",
                "as": "event_end",
            },
        ],
    }
    for k, v in override_chart_specs.items():
        chart_specs[k] = v
    return chart_specs
