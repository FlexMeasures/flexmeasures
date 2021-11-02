from flexmeasures.data.models.charts.defaults import ENCODING_TITLES


def bar_chart(title: str, quantity: str = "unknown quantity", unit: str = "a.u."):
    if not unit:
        unit = "a.u."
    return {
        "description": "A simple bar chart.",
        "title": title,
        "mark": "bar",
        "encoding": {
            "x": {
                "field": "event_start",
                "type": "T",
                "title": ENCODING_TITLES["event_start"],
            },
            "y": {
                "field": "event_value",
                "type": "quantitative",
                "title": quantity + " (" + unit + ")",
                "stack": None,
            },
            "color": {
                "field": "source",
                "type": "ordinal",
                "title": ENCODING_TITLES["source"],
            },
            "opacity": {"value": 0.7},
            "tooltip": [
                {
                    "field": "event_value",
                    "title": quantity + " (" + unit + ")",
                    "type": "quantitative",
                },
                {
                    "field": "full_date",
                    "title": ENCODING_TITLES["full_date"],
                    "type": "nominal",
                },
                {
                    "field": "source",
                    "title": ENCODING_TITLES["source"],
                    "type": "ordinal",
                },
            ],
        },
    }
