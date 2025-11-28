"""
These descriptions are used in documentation/features/scheduling.rst and in OpenAPI.
If you need to use a new .rst directive, update make_openapi_compatible accordingly, so it shows up nicely in OpenAPI.
For instance:
- the :abbr:`X (Y)` directive is converted to a <abbr title="Y">X</abbr> HTML tag.
- any footnote references, such as [#quantity_field]_, are stripped
  (these are meant for .rst docs to explain field types, which in OpenAPI is redundant,
  given that each field is already documented as being of an explicit type).
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


# FLEX-CONTEXT


INFLEXIBLE_DEVICE_SENSORS = MetaData(
    description="""Power sensors representing devices that are relevant, but not flexible in the timing of their demand/supply.
For example, a sensor recording rooftop solar power that is connected behind the main meter, and whose production falls under the same contract as the flexible device(s) being scheduled.
Their power demand cannot be adjusted but still matters for finding the best schedule for other devices.
Must be a list of integers.
""",
    example=[3, 4],
)
COMMITMENTS = MetaData(
    description="Prior commitments. Support for this field in the UI is still under further development, but you can study the code to learn more.",
    example=[],
)
CONSUMPTION_PRICE = MetaData(
    description="The electricity price applied to the site's aggregate consumption. Can be (a sensor recording) market prices, but also CO₂ intensity—whatever fits your optimization problem. [#old_consumption_price_field]_",
    example={"sensor": 5},
    # examples=[{"sensor": 5}, "0.29 EUR/kWh"],  # todo: waiting for https://github.com/marshmallow-code/apispec/pull/999
)
PRODUCTION_PRICE = MetaData(
    description="The electricity price applied to the site's aggregate production. Can be (a sensor recording) market prices, but also CO₂ intensity—whatever fits your optimization problem, as long as the unit matches the ``consumption-price`` unit. [#old_production_price_field]_",
    example="0.12 EUR/kWh",
)
SITE_POWER_CAPACITY = MetaData(
    description="""Maximum achievable power at the site's grid connection point, in either direction.
Becomes a hard constraint in the optimization problem, which is especially suitable for physical limitations. [#asymmetric]_ [#minimum_capacity_overlap]_
""",
    example="45kVA",
)
SITE_CONSUMPTION_CAPACITY = MetaData(
    description="""Maximum consumption power at the site's grid connection point.
If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-consumption-capacity`` will be used. [#consumption]_
If a ``site-consumption-breach-price`` is defined, the ``site-consumption-capacity`` becomes a soft constraint in the optimization problem.
Otherwise, it becomes a hard constraint. [#minimum_capacity_overlap]_
""",
    example="45kW",
)
SITE_PRODUCTION_CAPACITY = MetaData(
    description="""Maximum production power at the site's grid connection point.
If ``site-power-capacity`` is defined, the minimum between the ``site-power-capacity`` and ``site-production-capacity`` will be used. [#production]_
If a ``site-production-breach-price`` is defined, the ``site-production-capacity`` becomes a soft constraint in the optimization problem.
Otherwise, it becomes a hard constraint. [#minimum_capacity_overlap]_
""",
    example="0kW",
)
SITE_PEAK_CONSUMPTION = MetaData(
    description="""The site's previously achieved achieved peak consumption.
This value forms the baseline for new peak charges, since any peaks up to this level represent sunk costs.
Defaults to 0 kW.
""",
    example={"sensor": 7},
)
SITE_PEAK_CONSUMPTION_PRICE = MetaData(
    description="""Per-kW price applied to any consumption that exceeds the site's previously achieved peak consumption.
This price reflects the cost of increasing the site’s peak further and is used by the scheduler to motivate peak shaving.
It must use the same currency as the other price settings and cannot be negative.
For large connections, this price is usually stated explicitly on the tariff sheets of their network operator. [#penalty_field]_
""",
    example="260 EUR/MW",
)
SITE_PEAK_PRODUCTION = MetaData(
    description="""The site's previously achieved achieved peak production.
This value forms the baseline for new peak charges, since any peaks up to this level represent sunk costs.
Defaults to 0 kW.
""",
    example={"sensor": 8},
)
SITE_PEAK_PRODUCTION_PRICE = MetaData(
    description="""Per-kW price applied to any production that exceeds the site's previously achieved peak production.
This price reflects the cost of increasing the site’s peak further and is used by the scheduler to motivate peak shaving.
It must use the same currency as the other price settings and cannot be negative.
For large connections, this price is usually stated explicitly on the tariff sheets of their network operator. [#penalty_field]_
""",
    example="260 EUR/MW",
)
SOC_MINIMA_BREACH_PRICE = MetaData(
    description="""This **penalty value** is used to discourage the violation of **soc-minima** constraints in the flex-model, which the scheduler will attempt to minimize.
It must use the same currency as the other price settings and cannot be negative.
While it's an internal nudge to steer the scheduler—and doesn't represent a real-life cost—it should still be chosen in proportion to the actual energy prices at your site.
If it's too high, it will overly dominate other constraints; if it's too low, it will have no effect.
Without this value, the soc-minima become hard constraints, which means that any infeasible state-of-charge minima would prevent a complete schedule from being computed. [#penalty_field]_ [#breach_field]_
""",
    example="120 EUR/kWh",
)
SOC_MAXIMA_BREACH_PRICE = MetaData(
    description="""This **penalty value** is used to discourage the violation of **soc-maxima** constraints in the flex-model, which the scheduler will attempt to minimize.
It must use the same currency as the other price settings and cannot be negative.
While it's an **internal nudge** to steer the scheduler—and doesn't represent a real-life cost—it should still be chosen in proportion to the actual energy prices at your site.
If it's too high, it will overly dominate other constraints; if it's too low, it will have no effect.
Without this value, the soc-maxima become hard constraints, which means that any infeasible state-of-charge maxima would prevent a complete schedule from being computed. [#penalty_field]_ [#breach_field]_
""",
    example="120 EUR/kWh",
)
CONSUMPTION_BREACH_PRICE = MetaData(
    description="""This **penalty value** is used to discourage the violation of the **consumption-capacity** constraint in the flex-model.
It effectively treats the capacity as a **soft constraint**, allowing the scheduler to exceed it when necessary but with a high cost.
The scheduler will attempt to minimize this cost.
It must use the same currency as the other price settings and cannot be negative. [#penalty_field]_ [#breach_field]_
""",
    example="10 EUR/kW",
)
PRODUCTION_BREACH_PRICE = MetaData(
    description="""This **penalty value** is used to discourage the violation of the **production-capacity** constraint in the flex-model.
It effectively treats the capacity as a **soft constraint**, allowing the scheduler to exceed it when necessary but with a high cost.
The scheduler will attempt to minimize this cost.
It must use the same currency as the other price settings and cannot be negative. [#penalty_field]_ [#breach_field]_
""",
    example="10 EUR/kW",
)
RELAX_CONSTRAINTS = MetaData(
    description="""If True (default is ``False``), several constraints are relaxed by setting default breach prices within the optimization problem, leading to the default priority:

1. Avoid breaching the site consumption/production capacity.
2. Avoid not meeting SoC minima/maxima.
3. Avoid breaching the desired device consumption/production capacity.

We recommend to set this field to ``True`` to enable the default prices and associated priorities as defined by FlexMeasures.
For tighter control over prices and priorities, the breach prices can also be set explicitly (the relevant fields have **breach-price** in their name).
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
    description="""This **penalty value** is used to discourage the violation of the **site-consumption-capacity** constraint in the flex-context.
It effectively treats the capacity as a **soft constraint**, allowing the scheduler to exceed it when necessary but with a high cost.
The scheduler will attempt to minimize this cost.
It must use the same currency as the other price settings and cannot be negative.
The field may define (a sensor recording) contractual penalties, or a theoretical penalty influencing how badly breaches should be avoided. [#penalty_field]_ [#breach_field]_
""",
    example="1000 EUR/kW",
)
SITE_PRODUCTION_BREACH_PRICE = MetaData(
    description="""This **penalty value** is used to discourage the violation of the **site-production-capacity** constraint in the flex-context.
It effectively treats the capacity as a **soft constraint**, allowing the scheduler to exceed it when necessary but with a high cost.
The scheduler will attempt to minimize this cost.
It must use the same currency as the other price settings and cannot be negative.
The field may define (a sensor recording) contractual penalties, or a theoretical penalty influencing how badly breaches should be avoided. [#penalty_field]_ [#breach_field]_"
""",
    example="1000 EUR/kW",
)


# FLEX-MODEL


STATE_OF_CHARGE = MetaData(
    description="Sensor used to record the scheduled state of charge.",
    example={"sensor": 12},
)
SOC_AT_START = MetaData(
    description="""The (estimated) state of charge at the beginning of the schedule (for storage devices, this defaults to 0).
Usually added to each scheduling request. [#quantity_field]_
""",
    example="3.1 kWh",
)
SOC_UNIT = MetaData(
    description="""[Deprecated field] The unit used to interpret any SoC related flex-model value that does not mention a unit itself (only applies to numeric values, so not to string values).
To avoid using this field, mention the unit in each field explicitly (for instance, ``"3.1 kWh"`` rather than ``3.1``).
Only kWh and MWh are allowed.
""",
    example="kWh",
)
SOC_MIN = MetaData(
    description="""A constant and non-negotiable lower boundary for all values in the schedule (for storage devices, this defaults to 0).
If used, this is regarded as an unsurpassable physical limitation.
To set softer boundaries, use the **soc-minima** flex-model field instead together with the **soc-minima-breach-price`` field in the flex-context. [#quantity_field]_
""",
    example="2.5 kWh",
)
SOC_MAX = MetaData(
    description="""A constant and non-negotiable upper boundary for all values in the schedule (for storage devices, this defaults to max soc-target, if that is provided).
If used, this is regarded as an unsurpassable physical limitation.
To set softer boundaries, use the **soc-maxima** flex-model field instead together with the **soc-maxima-breach-price`` field in the flex-context. [#quantity_field]_
""",
    example="7 kWh",
)
SOC_MINIMA = MetaData(
    description="""Set points that form lower boundaries, e.g. to target a full car battery in the morning.
If a ``soc-minima-breach-price`` is defined, the ``soc-minima`` become soft constraints in the optimization problem.
Otherwise, they become hard constraints. [#maximum_overlap]_""",
    example=[{"datetime": "2024-02-05T08:00:00+01:00", "value": "8.2 kWh"}],
)
SOC_MAXIMA = MetaData(
    description="""Set points that form upper boundaries at certain times, e.g. to target an empty heat buffer before a maintenance window.
If a ``soc-maxima-breach-price`` is defined, the ``soc-maxima`` become soft constraints in the optimization problem.
Otherwise, they become hard constraints. [#minimum_overlap]_""",
    example={
        "value": "51 kWh",
        "start": "2024-02-05T12:00:00+01:00",
        "end": "2024-02-05T13:30:00+01:00",
    },
)
SOC_TARGETS = MetaData(
    description="Exact set point(s) that the scheduler needs to realize.",
    example=[{"datetime": "2024-02-05T08:00:00+01:00", "value": "3.2 kWh"}],
)
SOC_GAIN = MetaData(
    description="""SoC gain per time step, e.g. from a secondary energy source. Useful if energy is inserted by an external process (in-flow).
This field allows setting multiple components, either fixed or dynamic, which add up to an aggregated gain.
This field represents an energy flow (for instance, in kW) rather than saying something about an (allowed) energy state (for instance, in kWh).
The SoC gain is unaffected by the charging efficiency.
""",
    example=["100 Wh/h", {"sensor": 34}],
)
SOC_USAGE = MetaData(
    description="""SoC drain per time step, e.g. from a load or heat sink.
Useful if energy is extracted by an external process or there are dissipating losses (out-flow).
This field allows setting multiple components, either fixed or dynamic, which add up to an aggregated usage.
This field represents an energy flow (for instance, in kW) rather than saying something about an (allowed) energy state (for instance, in kWh).
The SoC drain is unaffected by the discharging efficiency.
""",
    example=["100 Wh/h", {"sensor": 23}],
)
ROUNDTRIP_EFFICIENCY = MetaData(
    description="""Below 100%, this represents roundtrip losses (of charging & discharging), usually used for batteries.
Can be a percentage or a ratio in the range [0,1].
Defaults to 100% (no roundtrip loss). [#quantity_field]_
""",
    example="90%",
)
CHARGING_EFFICIENCY = MetaData(
    description="""One-way conversion efficiency from electricity to the storage's state of charge.
Can be a percentage, a ratio in the range [0,1], or a coefficient of performance (>1).
Defaults to 100% (no conversion loss).
""",
    example=".9",
)
DISCHARGING_EFFICIENCY = MetaData(
    description="""One-way conversion efficiency from the storage's state of charge to electricity.
Defaults to 100% (no conversion loss).""",
    example="90%",
)
STORAGE_EFFICIENCY = MetaData(
    description="""The efficiency of keeping the storage's state of charge at its present level, used to encode losses over time.
As a result, each time step the energy is held longer leads to higher losses.
This setting is crucial to some sorts of energy storage, e.g. thermal buffers.
To give an example, when this setting is at 95% (or 0.95), this means a loss of 5% per time step. Defaults to 100% (no storage loss over time).
Note that the storage efficiency used by the scheduler is applied over each time step equal to the sensor resolution.
For example, a storage efficiency of 95 percent per (absolute) day, for scheduling a 1-hour resolution sensor, should be passed as a storage efficiency of :math:`0.95^{1/24} = 0.997865`.
""",
    example="99.9%",
)
PREFER_CHARGING_SOONER = MetaData(
    description="""Tie-breaking policy to apply if conditions are stable, which signals a preference to charge sooner rather than later (defaults to True).
It also signals a preference to discharge later.
Boolean option only.
""",
    example=True,
)
PREFER_CURTAILING_LATER = MetaData(
    description="""Tie-breaking policy to apply if conditions are stable, which signals a preference to curtail both consumption and production later, whichever is applicable (defaults to True).
Boolean option only.
""",
    example=True,
)
POWER_CAPACITY = MetaData(
    description="Device-level power constraint. How much power can be applied to this asset. [#minimum_overlap]_",
    example="50 kVA",
)
CONSUMPTION_CAPACITY = MetaData(
    description="Device-level power constraint on consumption. How much power can be drawn by this asset. [#minimum_overlap]_",
    example={"sensor": 56},
)
PRODUCTION_CAPACITY = MetaData(
    description="""Device-level power constraint on production.
How much power can be supplied by this asset.
For :abbr:`PV (photovoltaic solar panels)` curtailment, set this to reference your sensor containing PV power forecasts. [#minimum_overlap]_
""",
    example="0 kW",
)
