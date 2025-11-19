"""
These descriptions are used in documentation/features/scheduling.rst and in OpenAPI.
If you need to use a new .rst directive, update make_openapi_compatible accordingly, so it shows up nicely in OpenAPI.
For instance, the :abbr:`X (Y)` directive is converted to a <abbr title="Y">X</abbr> HTML tag.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class MetaData:
    description: str
    example: Any = None
    examples: Any = None

    def to_dict(self):
        """Do not include empty fields."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


### FLEX-CONTEXT ###


INFLEXIBLE_DEVICE_SENSORS = MetaData(
    description="Power sensors that are relevant, but not flexible, such as a sensor recording rooftop solar power connected behind the main meter, whose production falls under the same contract as the flexible device(s) being scheduled. Their power demand cannot be adjusted but still matters for finding the best schedule for other devices. Must be a list of integers.",
    example=[3, 4],
)
COMMITMENTS = MetaData(
    description="Prior commitments.",
    example=[],
)
CONSUMPTION_PRICE = MetaData(
    description="The price of consuming energy. Can be (a sensor recording) market prices, but also CO₂ intensity—whatever fits your optimization problem. (This field replaced the ``consumption-price-sensor`` field.)",
    example={"sensor": 5},
    # examples=[{"sensor": 5}, "0.29 EUR/kWh"],  # todo: waiting for https://github.com/marshmallow-code/apispec/pull/999
)
PRODUCTION_PRICE = MetaData(
    description="The price of producing energy. Can be (a sensor recording) market prices, but also CO₂ intensity—whatever fits your optimization problem, as long as the unit matches the ``consumption-price`` unit. (This field replaced the ``production-price-sensor`` field.)",
    example="0.12 EUR/kWh",
)
SITE_POWER_CAPACITY = MetaData(
    description="Maximum achievable power at the grid connection point, in either direction. Becomes a hard constraint in the optimization problem, which is especially suitable for physical limitations.",
    example="45kVA",
)
SITE_CONSUMPTION_CAPACITY = MetaData(
    description="Maximum consumption power at the grid connection point. If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-consumption-capacity`` will be used. If a ``site-consumption-breach-price`` is defined, the ``site-consumption-capacity`` becomes a soft constraint in the optimization problem. Otherwise, it becomes a hard constraint.",
    example="45kW",
)
SITE_PRODUCTION_CAPACITY = MetaData(
    description="Maximum production power at the grid connection point. If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-production-capacity`` will be used. If a ``site-production-breach-price`` is defined, the ``site-production-capacity`` becomes a soft constraint in the optimization problem. Otherwise, it becomes a hard constraint.",
    example="0kW",
)
SITE_PEAK_CONSUMPTION = MetaData(
    description="Current peak consumption. Costs from peaks below it are considered sunk costs. Default to 0 kW.",
    example={"sensor": 7},
)
SITE_PEAK_CONSUMPTION_PRICE = MetaData(
    description="Consumption peaks above the ``site-peak-consumption`` are penalized against this per-kW price.",
    example="260 EUR/MW",
)
SITE_PEAK_PRODUCTION = MetaData(
    description="Current peak production. Costs from peaks below it are considered sunk costs. Default to 0 kW.",
    example={"sensor": 8},
)
SITE_PEAK_PRODUCTION_PRICE = MetaData(
    description="Production peaks above the ``site-peak-production`` are penalized against this per-kW price.",
    example="260 EUR/MW",
)
SOC_MINIMA_BREACH_PRICE = MetaData(
    description="Penalty for not meeting ``soc-minima`` defined in the flex-model.",
    example="120 EUR/kWh",
)
SOC_MAXIMA_BREACH_PRICE = MetaData(
    description="Penalty for not meeting ``soc-maxima`` defined in the flex-model.",
    example="120 EUR/kWh",
)
CONSUMPTION_BREACH_PRICE = MetaData(
    description="The price of breaching the ``consumption-capacity`` in the flex-model, useful to treat ``consumption-capacity`` as a soft constraint but still make the scheduler attempt to respect it.",
    example="10 EUR/kW",
)
PRODUCTION_BREACH_PRICE = MetaData(
    description="The price of breaching the ``production-capacity`` in the flex-model, useful to treat ``production-capacity`` as a soft constraint but still make the scheduler attempt to respect it.",
    example="10 EUR/kW",
)
RELAX_CONSTRAINTS = MetaData(
    description="""If True (default is ``False``), several constraints are relaxed by setting default breach prices within the optimization problem, leading to the default priority:

1. Avoid breaching the site consumption/production capacity.
2. Avoid not meeting SoC minima/maxima.
3. Avoid breaching the desired device consumption/production capacity.

We recommend to set this field to ``True`` to enable the default prices and associated priorities as defined by FlexMeasures. For tighter control over prices and priorities, the breach prices can also be set explicitly (see below).
""",
    example=True,
)
RELAX_SOC_CONSTRAINTS = MetaData(
    description="If True, avoids not meeting SoC minima/maxima as a relaxed constraint.",
    example=True,
)
RELAX_CAPACITY_CONSTRAINTS = MetaData(
    description="If True, avoids breaching the desired device consumption/production capacity as a relaxed constraint.",
    example=True,
)
RELAX_SITE_CAPACITY_CONSTRAINTS = MetaData(
    description="If True, avoids breaching the site consumption/production capacity as a relaxed constraint.",
    example=True,
)
SITE_CONSUMPTION_BREACH_PRICE = MetaData(
    description="The price of breaching the ``site-consumption-capacity``, useful to treat ``site-consumption-capacity`` as a soft constraint but still make the scheduler attempt to respect it. Can be (a sensor recording) contractual penalties, but also a theoretical penalty just to allow the scheduler to breach the consumption capacity, while influencing how badly breaches should be avoided.",
    example="1000 EUR/kW",
)
SITE_PRODUCTION_BREACH_PRICE = MetaData(
    description="The price of breaching the ``site-production-capacity``, useful to treat ``site-production-capacity`` as a soft constraint but still make the scheduler attempt to respect it. Can be (a sensor recording) contractual penalties, but also a theoretical penalty just to allow the scheduler to breach the production capacity, while influencing how badly breaches should be avoided.",
    example="1000 EUR/kW",
)


### FLEX-MODEL ###
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
