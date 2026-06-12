chart_options = dict(
    mode="vega-lite",
    # canvas renders dense time series much faster than svg (no per-mark DOM nodes)
    renderer="canvas",
    # fetch chart specs (and any data the spec references) fresh on every load,
    # so performance reports measure real network calls rather than cache hits
    loader={"http": {"cache": "no-store"}},
    actions={"export": True, "source": False, "compiled": False, "editor": False},
    theme="light",
    tooltip={"theme": "light"},
)
