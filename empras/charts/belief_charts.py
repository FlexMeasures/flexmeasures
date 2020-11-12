bar_chart = {
    "description": "A simple bar chart.",
    "mark": "bar",
    "encoding": {
        "x": {"field": "dt", "type": "T"},
        "y": {"field": "k", "type": "quantitative"},
        "tooltip": [
            {"field": "full_date", "title": "Time and date", "type": "nominal"},
            {"field": "k", "title": "Consumption rate", "type": "quantitative"},
        ],
    },
}
