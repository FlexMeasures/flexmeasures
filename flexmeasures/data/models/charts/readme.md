# Developer docs for adding chart specs

Chart specs can be specified as a dictionary with a vega-lite specification or as an altair chart.
Alternatively, they can be specified as a function that returns a dict (with vega-lite specs) or an altair chart.
This approach is useful if you need to parameterize the specification with kwargs.

Todo: support a plug-in architecture, see https://packaging.python.org/guides/creating-and-discovering-plugins/

The chart types an asset chart can be drawn as are listed in `chart_types.py`, the registry of asset chart types.
To add one, add an entry there: its public, kebab-case name, the assets it applies to, its layout (the graphs it draws) and the function that builds its chart specs.
