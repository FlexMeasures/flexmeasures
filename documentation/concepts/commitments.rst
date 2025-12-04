Commitments
===========

Overview
--------

A **Commitment** is the central economic abstraction used by FlexMeasures to
express *soft constraints, preferences and market positions* in the scheduler.

A commitment describes:

- a **baseline quantity** over time (the target or assumed position), and
- marginal prices for **upwards** and **downwards deviations** from that baseline.

The scheduler converts all provided commitments into terms in the optimization
objective function so that the solver *minimizes the total deviation cost*
across the schedule horizon. Absolute physical limits (for example generator or
line capacities) are *not* modelled as commitments — those are enforced as
Pyomo constraints.

Key properties
--------------

Each Commitment has the following important attributes (high level):

- ``name`` — a logical string identifier (e.g. ``"energy"``, ``"production peak"``).
- ``device`` — optional: restricts the commitment to a single device; otherwise
  it is an EMS/site-level commitment.
- ``index`` — the DatetimeIndex (time grid) on which the series are defined.
- ``quantity`` — the baseline Series (per slot or per group).
- ``upwards_deviation_price`` — Series defining marginal cost/reward for upward deviations.
- ``downwards_deviation_price`` — Series defining marginal cost/reward for downward deviations.
- ``_type`` — grouping indicator: ``'each'`` or ``'any'`` (see Grouping below).

Sign convention (flows vs stocks)
--------------------------------

- **Flow commitments** (e.g. power/energy flows):

  - A *positive* baseline quantity denotes **consumption**.

    - Actual > baseline → *upwards* deviation (more consumption).
    - Actual < baseline → *downwards* deviation (less consumption).
  - A *negative* baseline quantity denotes **production** (feed-in).

    - Actual less negative (i.e. closer to zero) → *upwards* deviation (less production).
    - Actual more negative → *downwards* deviation (more production).

- **Stock commitments** (e.g. state of charge for storage):

  - ``quantity`` is the target stock level; deviations above/below that target
    are priced via the upwards/downwards price series.

Soft vs hard semantics
----------------------

Commitments in FlexMeasures are **soft** by design: they represent economic
penalties or rewards that the optimizer considers when building schedules.
Hard operational constraints (such as physical power limits or strict device
interlocks) are expressed separately as Pyomo constraints in the scheduling
model. If a “hard” behaviour is required from a commitment, assign very large
penalty prices, but prefer modelling non-negotiable limits as Pyomo constraints.

Converting flex-context fields into commitments
-----------------------------------------------

Users may supply preferences and price fields in the ``flex-context``. The
scheduler translates the relevant fields into one or more `Commitment` objects
before calling the optimizer.

Typical translations include:

- tariffs (``consumption-price``, ``production-price``) → an ``"energy"`` FlowCommitment with zero baseline so net consumption/production is priced;
- peak/excess limits (``site-peak-production``, ``site-peak-production-price``, etc.) → dedicated peak FlowCommitment(s);
- storage-related fields (``soc-minima``, ``soc-minima-breach-price``, etc.) → StockCommitment(s).

A short example
---------------

Below is a compact example showing how the scheduler conceptually creates an
``"energy"`` flow commitment from a (per-slot) tariff:

.. code-block:: python

    from pandas import Series, date_range
    from flexmeasures.data.models.planning import FlowCommitment

    index = date_range(start="2025-01-01 00:00", periods=24, freq="H")
    # zero baseline → the asset may consume or produce; deviations are priced.
    baseline = Series(0.0, index=index)

    # consumption and production tariffs (per kWh)
    consumption_price = Series(0.20, index=index)  # 0.20 EUR/kWh for consumption
    production_price = Series(-0.05, index=index)  # -0.05 EUR/kWh reward for production

    energy_commitment = FlowCommitment(
        name="energy",
        index=index,
        quantity=baseline,
        upwards_deviation_price=consumption_price,
        downwards_deviation_price=production_price,
        _type="each"
    )

The scheduler sets up such commitments (site-level and device-level) and, together with any prior commitments, hands them to the linear optimizer.

Examples (commitments commonly derived from flex-context)
--------------------------------------------------------

The examples below map the most common `flex-context` semantics to the
commitments the scheduler constructs.

1. **Energy (tariff)**

   - *Fields used*: ``consumption-price``, ``production-price``.
   - *Commitment*: Flow commitment named ``"energy"`` with zero baseline and
     the two price series as upwards/downwards deviation prices.

2. **Peak consumption**

   - *Fields used*: ``site-peak-consumption`` (baseline) and ``site-peak-consumption-price`` (upwards-deviation price); the downwards price is set to ``0``.
   - *Commitment*: Flow commitment named ``"consumption peak"``; positive baseline
     values denote the prior consumption peak associated with sunk costs, and the upwards price penalises going beyond that baseline.

3. **Peak production / peak feed-in**

   - *Fields used*: ``site-peak-production`` (baseline) and ``site-peak-production-price`` (downwards-deviation price); the upwards price is set to ``0``.
   - *Commitment*: Flow commitment named ``"production peak"``; negative baseline
     values denote the prior production peak associated with sunk costs, and the downwards price penalises going beyond that baseline.

4. **Consumption capacity**

   - *Fields used*: ``site-consumption-capacity`` (baseline), and ``site-consumption-breach-price`` (upwards-deviation price); the downwards price is set to ``0``.
   - *Commitment*: Flow commitment named ``"consumption breach"``; positive baseline
     values denote the allowed consumption limit and the upwards price penalises going
     beyond that limit.

5. **Production capacity**

   - *Fields used*: ``site-production-capacity`` (baseline) and ``site-production-breach-price`` (downwards-deviation price); the upwards price is set to ``0``.
   - *Commitment*: Flow commitment named ``"production breach"``; negative baseline
     values denote the allowed production limit and the downwards price penalises going
     beyond that limit.

6. **SOC minima / maxima (storage preferences)**

   - *Fields used*: ``soc-minima``, ``soc-minima-breach-price``, ``soc-maxima`` and ``soc-maxima-breach-price``.
   - *Commitment*: StockCommitment(s) that price deviations below minima or
     above maxima. Hard storage capacities are set through ``soc-min`` and ``soc-max`` instead and are modelled as Pyomo constraints.

7. **Power bands per device**

   - *Fields used*: ``consumption-capacity`` and ``production-capacity`` (baselines), ``consumption-breach-price`` (upwards-deviation price, with 0 downwards) and ``production-breach-price`` (downwards-deviation price, with 0 upwards).
   - *Commitment*: FlowCommitment with either baseline and corresponding prices.

Grouping across time and devices
--------------------------------

- ``_type == 'each'``: penalise deviations per time slot (default for time series).
- ``_type == 'any'``: treat the whole commitment horizon as one group (useful
  for peak-style penalties where only the maximum over the window should be
  counted).

.. note::

   Near-term feature: support for **grouping over devices** is planned and
   documented here. When enabled, grouping over devices lets you express
   soft constraints that aggregate deviations across a set of devices,
   for example, an intermediate capacity constraint from a feeder shared by a group of devices (via **flow commitments**), or multiple power-to-heat devices that feed a shared thermal buffer (via **stock commitments**).
