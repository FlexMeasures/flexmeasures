"""Versions of the third-party assets which the UI serves itself, from static/vendor/<lib>/<version>/.

Each key is also the library's directory name under static/vendor/.
Templates load these assets through the macros in templates/includes/vendor.html.
To bump a library, see static/vendor/README.md.
This is a leaf module, so flexmeasures/ui/__init__.py can import it without an import cycle.
"""

JS_VERSIONS: dict[str, str] = {
    # Keys kept from the deprecated FLEXMEASURES_JS_VERSIONS setting, which plugin templates may read.
    "vega": "5.22.1",
    "vegaembed": "6.21.0",
    "vegalite": "5.5.0",  # "5.6.0" has a problematic bar chart: see our sensor page and https://github.com/vega/vega-lite/issues/8496
    "echarts": "5.6.0",  # used for the fast (canvas-based) chart mode
    "currencysymbolmap": "5.1.0",
    "jsoneditor": "2.15.2",
    "leaflet": "1.9.4",
    "leafletmarkercluster": "1.5.3",
    "leafletmarkerclusterlayersupport": "2.0.1",
    # Previously hardcoded in templates.
    "jquery": "3.5.1",
    "floatthead": "2.2.1",
    "bootstrap": "5.3.3",
    "bootstrapicons": "1.10.5",
    "fontawesome": "4.7.0",
    "ionrangeslider": "2.3.1",
    "datatables": "1.10.22",  # also referenced by path in static/css/flexmeasures.css, for the sort icons
    "d3": "6.7.0",
    "litepicker": "2.0.12",
    "jstimezonedetect": "1.0.7",
}
