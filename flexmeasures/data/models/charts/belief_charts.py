from flexmeasures.data.models.charts.defaults import FIELD_DEFINITIONS


def bar_chart(title: str, quantity: str = "unknown quantity", unit: str = "a.u."):
    if not unit:
        unit = "a.u."
    event_value_field_definition = dict(
        title=f"{quantity} ({unit})",
        format=".3s",
        stack=None,
        **FIELD_DEFINITIONS["event_value"],
    )
    return {
        "description": "A simple bar chart.",
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": FIELD_DEFINITIONS["event_start"],
            "y": event_value_field_definition,
            "color": FIELD_DEFINITIONS["source"],
            "opacity": {"value": 0.7},
            "tooltip": [
                FIELD_DEFINITIONS["full_date"],
                event_value_field_definition,
                FIELD_DEFINITIONS["source"],
            ],
        },
    }
