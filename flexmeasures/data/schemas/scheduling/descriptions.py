"""
These descriptions are used in documentation/features/scheduling.rst and in OpenAPI.
If you need to use a new .rst directive, update make_openapi_compatible accordingly, so it shows up nicely in OpenAPI.
For instance, the :abbr:`X (Y)` directive is converted to a <abbr title="Y">X</abbr> HTML tag.
"""

SOC_AT_START = (
    "The (estimated) state of charge at the beginning of the schedule (defaults to 0)."
)
SOC_UNIT = """The unit used to interpret any SoC related flex-model value that does not mention a unit itself (only applies to numeric values, so not to string values).
       However, we advise to mention the unit in each field explicitly (for instance, ``"3.1 kWh"`` rather than ``3.1``).
       Enumerated option only."""
CONSUMPTION_CAPACITY = "Device-level power constraint on consumption. How much power can be drawn by this asset."
PRODUCTION_CAPACITY = "Device-level power constraint on production. How much power can be supplied by this asset. For :abbr:`PV (photovoltaic solar panels)` curtailment, set this to reference your sensor containing PV power forecasts."
