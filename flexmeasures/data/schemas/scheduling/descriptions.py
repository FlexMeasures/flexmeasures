"""
These descriptions are used in documentation/features/scheduling.rst and in OpenAPI.
If you need to use a new .rst directive, update make_openapi_compatible accordingly, so it shows up nicely in OpenAPI.
For instance, the :abbr:`X (Y)` directive is converted to a <abbr title="Y">X</abbr> HTML tag.
"""

STATE_OF_CHARGE = "If given, the scheduled state of charge is stored on this sensor."
SOC_AT_START = (
    "The (estimated) state of charge at the beginning of the schedule (defaults to 0)."
)
SOC_UNIT = """The unit used to interpret any SoC related flex-model value that does not mention a unit itself (only applies to numeric values, so not to string values).
       However, we advise to mention the unit in each field explicitly (for instance, ``"3.1 kWh"`` rather than ``3.1``).
       Enumerated option only."""
SOC_MIN = "A constant and non-negotiable lower boundary for all values in the schedule (defaults to 0). If used, this is regarded as an unsurpassable physical limitation."
SOC_MAX = "A constant and non-negotiable upper boundary for all values in the schedule (defaults to max soc target, if provided). If used, this is regarded as an unsurpassable physical limitation."
SOC_MINIMA = "Set points that form user-defined lower boundaries, e.g. to target a full car battery in the morning (defaults to NaN values)."
SOC_MAXIMA = "Set points that form user-defined upper boundaries at certain times (defaults to NaN values)."
SOC_TARGETS = "Exact user-defined set point(s) that the scheduler needs to realize (defaults to NaN values)."
SOC_GAIN = "SoC gain per time step, e.g. from a secondary energy source (defaults to zero). Useful if energy is inserted by an external process (in-flow)."
SOC_USAGE = "SoC reduction per time step, e.g. from a load or heat sink (defaults to zero). Useful if energy is extracted by an external process or there are dissipating losses (out-flow)."
ROUNDTRIP_EFFICIENCY = "Below 100%, this represents roundtrip losses (of charging & discharging), usually used for batteries. Can be percent or ratio ``[0,1]`` (defaults to 100%)."
CHARGING_EFFICIENCY = "Apply efficiency losses only at time of charging, not across roundtrip (defaults to 100%)."
DISCHARGING_EFFICIENCY = "Apply efficiency losses only at time of discharging, not across roundtrip (defaults to 100%)."
STORAGE_EFFICIENCY = "This can encode losses over time, so each time step the energy is held longer leads to higher losses (defaults to 100%). Also read about applying this value per time step across longer time spans."
PREFER_CHARGING_SOONER = "Tie-breaking policy to apply if conditions are stable, which signals a preference to charge sooner rather than later (defaults to True). It also signals a preference to discharge later. Boolean option only."
PREFER_CURTAILING_LATER = "Tie-breaking policy to apply if conditions are stable, which signals a preference to curtail both consumption and production later, whichever is applicable (defaults to True). Boolean option only."
POWER_CAPACITY = "Device-level power constraint. How much power can be applied to this asset (defaults to the Sensor attribute ``capacity_in_mw``)."
CONSUMPTION_CAPACITY = "Device-level power constraint on consumption. How much power can be drawn by this asset."
PRODUCTION_CAPACITY = "Device-level power constraint on production. How much power can be supplied by this asset. For :abbr:`PV (photovoltaic solar panels)` curtailment, set this to reference your sensor containing PV power forecasts."
