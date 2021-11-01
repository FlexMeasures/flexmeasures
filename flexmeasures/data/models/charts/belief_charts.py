from flexmeasures.data.models.charts.defaults import (
    SOURCE_TITLE,
    TIME_TITLE,
    TIME_TOOLTIP_TITLE,
)


def bar_chart(title: str, quantity: str = "unknown quantity", unit: str = "a.u."):
    if not unit:
        unit = "a.u."
    return {
        "description": "A simple bar chart.",
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": {"field": "event_start", "type": "T", "title": TIME_TITLE},
            "y": {
                "field": "event_value",
                "type": "quantitative",
                "title": quantity + " (" + unit + ")",
                "stack": None,
            },
            "color": {
                "field": "source",
                "type": "ordinal",
                "title": SOURCE_TITLE,
            },
            "opacity": {"value": 0.7},
            "tooltip": [
                {
                    "field": "event_value",
                    "title": quantity + " (" + unit + ")",
                    "type": "quantitative",
                },
                {"field": "full_date", "title": TIME_TOOLTIP_TITLE, "type": "nominal"},
                {"field": "source", "title": SOURCE_TITLE, "type": "ordinal"},
            ],
        },
    }
