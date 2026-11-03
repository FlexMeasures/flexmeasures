# Developer docs for adding chart specs

A chart type is a function in `belief_charts` that returns a dict (with vega-lite specs) or an altair chart.
Parameterize the specification with kwargs.

Only the sensor chart types listed in `SENSOR_CHART_TYPES` (in `charts/__init__.py`) are built,
so list a new sensor chart type there to make it available to chart requests.
`chart_type_to_chart_specs` applies the FlexMeasures defaults (see `defaults.py`) to a copy of the specs.

Todo: support a plug-in architecture, see https://packaging.python.org/guides/creating-and-discovering-plugins/

The chart types an asset chart can be drawn as are listed in `chart_types.py`, the registry of asset chart types.
To add one, add an entry there: its public, kebab-case name, the assets it applies to, its layout (the graphs it draws) and the function that builds its chart specs.
