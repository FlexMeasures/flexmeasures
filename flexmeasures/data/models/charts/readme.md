# Developer docs for adding chart specs

A chart builder is a function in `belief_charts` that returns a dict (with vega-lite specs) or an altair chart.
Parameterize the specification with kwargs.

Only the chart types listed in the registries in `chart_types.py` are built,
so register a new chart type there to make it available to chart requests.
There is one registry for the chart types of an asset (`ASSET_CHART_TYPES`) and one for those of a sensor (`SENSOR_CHART_TYPES`).
Each chart type has a public, kebab-case name, the assets or sensors it applies to, and the function that builds its chart specs;
an asset chart type also has a layout (the graphs it draws).
Legacy names, which the chart endpoints took before the chart types had public names, map to the public names and are still accepted.
`chart_type_to_chart_specs` builds a sensor chart type, applying the FlexMeasures defaults (see `defaults.py`) to a copy of the specs.

Plugins add their own chart types with `register_asset_chart_type` and `register_sensor_chart_type`,
when they are set up (see "Adding your own chart types" in `documentation/plugin/customisation.rst`).
The asset and sensor pages offer the registered chart types that apply,
and the fast chart (`fast-chart.js`) draws only the built-in ones, leaving the others to Vega-Lite.
