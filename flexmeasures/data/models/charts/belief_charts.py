from flexmeasures.data.models.charts.defaults import TIME_TITLE, TIME_TOOLTIP_TITLE


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
            },
            "tooltip": [
                {"field": "full_date", "title": TIME_TOOLTIP_TITLE, "type": "nominal"},
                {
                    "field": "event_value",
                    "title": quantity + " (" + unit + ")",
                    "type": "quantitative",
                },
            ],
        },
    }
