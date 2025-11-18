"""
These descriptions are used in documentation/features/scheduling.rst and in OpenAPI.
If you need to use a new .rst directive, update make_openapi_compatible accordingly, so it shows up nicely in OpenAPI.
For instance, the :abbr:`X (Y)` directive is converted to a <abbr title="Y">X</abbr> HTML tag.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class MetaData:
    description: str
    example: Any


STATE_OF_CHARGE = MetaData(
    description="If given, the scheduled state of charge is stored on this sensor.",
    example={"sensor": 12},
)
SOC_AT_START = MetaData(
    description="The (estimated) state of charge at the beginning of the schedule (defaults to 0).",
    example="3.1 kWh",
)
SOC_UNIT = MetaData(
    description="""The unit used to interpret any SoC related flex-model value that does not mention a unit itself (only applies to numeric values, so not to string values).
       However, we advise to mention the unit in each field explicitly (for instance, ``"3.1 kWh"`` rather than ``3.1``).
       Only kWh and MWh are allowed.""",
    example="kWh",
)
SOC_MIN = MetaData(
    description="A constant and non-negotiable lower boundary for all values in the schedule (defaults to 0). If used, this is regarded as an unsurpassable physical limitation.",
    example="2.5 kWh",
)
SOC_MAX = MetaData(
    description="A constant and non-negotiable upper boundary for all values in the schedule (defaults to max soc target, if provided). If used, this is regarded as an unsurpassable physical limitation.",
    example="7 kWh",
)
SOC_MINIMA = MetaData(
    description="Set points that form user-defined lower boundaries, e.g. to target a full car battery in the morning (defaults to NaN values).",
    example=[{"datetime": "2024-02-05T08:00:00+01:00", "value": "8.2 kWh"}],
)
SOC_MAXIMA = MetaData(
    description="Set points that form user-defined upper boundaries at certain times (defaults to NaN values).",
    example={
        "value": "51 kWh",
        "start": "2024-02-05T12:00:00+01:00",
        "end": "2024-02-05T13:30:00+01:00",
    },
)
SOC_TARGETS = MetaData(
    description="Exact user-defined set point(s) that the scheduler needs to realize (defaults to NaN values).",
    example=[{"datetime": "2024-02-05T08:00:00+01:00", "value": "3.2 kWh"}],
)
SOC_GAIN = MetaData(
    description="SoC gain per time step, e.g. from a secondary energy source (defaults to zero). Useful if energy is inserted by an external process (in-flow).",
    example=["100 W", {"sensor": 34}],
)
SOC_USAGE = MetaData(
    description="SoC reduction per time step, e.g. from a load or heat sink (defaults to zero). Useful if energy is extracted by an external process or there are dissipating losses (out-flow).",
    example=["100 W", {"sensor": 23}],
)
ROUNDTRIP_EFFICIENCY = MetaData(
    description="Below 100%, this represents roundtrip losses (of charging & discharging), usually used for batteries. Can be percent or ratio ``[0,1]`` (defaults to 100%).",
    example="90%",
)
CHARGING_EFFICIENCY = MetaData(
    description="Apply efficiency losses only at time of charging, not across roundtrip (defaults to 100%).",
    example=".9",
)
DISCHARGING_EFFICIENCY = MetaData(
    description="Apply efficiency losses only at time of discharging, not across roundtrip (defaults to 100%).",
    example="90%",
)
STORAGE_EFFICIENCY = MetaData(
    description="This can encode losses over time, so each time step the energy is held longer leads to higher losses (defaults to 100%). Also read about applying this value per time step across longer time spans.",
    example="99.9%",
)
PREFER_CHARGING_SOONER = MetaData(
    description="Tie-breaking policy to apply if conditions are stable, which signals a preference to charge sooner rather than later (defaults to True). It also signals a preference to discharge later. Boolean option only.",
    example=True,
)
PREFER_CURTAILING_LATER = MetaData(
    description="Tie-breaking policy to apply if conditions are stable, which signals a preference to curtail both consumption and production later, whichever is applicable (defaults to True). Boolean option only.",
    example=True,
)
POWER_CAPACITY = MetaData(
    description="Device-level power constraint. How much power can be applied to this asset (defaults to the Sensor attribute ``capacity_in_mw``).",
    example="50 kVA",
)
CONSUMPTION_CAPACITY = MetaData(
    description="Device-level power constraint on consumption. How much power can be drawn by this asset.",
    example={"sensor": 56},
)
PRODUCTION_CAPACITY = MetaData(
    description="Device-level power constraint on production. How much power can be supplied by this asset. For :abbr:`PV (photovoltaic solar panels)` curtailment, set this to reference your sensor containing PV power forecasts.",
    example="0 kW",
)
