# Developer docs for adding chart specs

A chart type is a function in `belief_charts` that returns a dict (with vega-lite specs) or an altair chart.
Parameterize the specification with kwargs.

Only the chart types listed in `SENSOR_CHART_TYPES` or `ASSET_CHART_BUILDERS` (in `charts/__init__.py`) are built,
so list a new chart type there to make it available to chart requests.
`chart_type_to_chart_specs` applies the FlexMeasures defaults (see `defaults.py`) to a copy of the specs.

Todo: support a plug-in architecture, see https://packaging.python.org/guides/creating-and-discovering-plugins/
