.. _commitments:

Commitments
===========

Commitments are a key concept in FlexMeasures' flexibility modeling. With commitments, you can express economic preferences and pre-existing market positions to the scheduler in a flexible way.
You can expand beyond only using one dynamic tariff signal, for example to also including peak prices and minimum fill rates. Or you can model passive imbalance.

Commitments are used in the background without you having to worry about them explicitly (you can use "syntactic sugar" in the ``flex-context`` to enjoy them).
However, they are also exposed as a powerful advanced tool to model your custom preferences or contracts.

This document explains what commitments are on a technical level, and then gives examples of how the scheduler uses them and how you can create your own commitments in the flex-context to great effect.

.. contents::
    :local:
    :depth: 1


What is a commitment?
---------------------

A **Commitment** is the economic abstraction FlexMeasures uses to express market positions and soft constraints (preferences) inside the scheduler.
They are a powerful modeling concept used in current flex-context fields, but can also model new circumstances.

.. admonition:: Examples of commitments
   :class: info-icon

   .. list-table::
      :widths: 55 45
      :header-rows: 1

      * - **Market positions**
        - **Soft constraints**
      * - - dynamic electricity tariffs
          - contracted (consumption|production) capacity
          - peak pricing
          - passive imbalance
          - PPAs
          - gas contracts
        - - Desired fill levels
          - Preferred power levels or idle states
          - Preference to advance charging and postpone discharging
          - Preference to postpone curtailment
          - CO₂ intensity

Commitments are converted to linear objective terms; all non-negotiable operational limits are modelled separately as Pyomo constraints.

A commitment describes:

- a **baseline quantity** over time (the contracted or preferred position), and
- marginal prices for **upwards** and **downwards deviations** from that baseline.

The scheduler converts all provided commitments into terms in the optimization
objective function so that the solver *minimizes the total deviation cost*
across the schedule horizon. Absolute physical limitations (for example generator or
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
---------------------------------

- **Flow commitments** (e.g. power/energy flows):

  - A *positive* baseline quantity denotes **consumption**.

    - Actual > baseline → *upwards* deviation (more consumption).
    - Actual < baseline → *downwards* deviation (less consumption).
  - A *negative* baseline quantity denotes **production** (feed-in).

    - Actual less negative (i.e. closer to zero) → *upwards* deviation (less production).
    - Actual more negative → *downwards* deviation (more production).

- **Stock commitments** (e.g. state of charge for storage):

  - ``quantity`` is the target stock level; deviations above/below that target
    are priced via the upwards/downwards price series, respectively.


How FlexMeasures uses commitments in the scheduler
--------------------------------------------------

Commitments in FlexMeasures are **soft** by design: they represent economic
penalties or rewards that the optimizer considers when building schedules.
Hard operational constraints (such as physical power limits or strict device
interlocks) are expressed separately as Pyomo constraints in the scheduling
model. If a “hard” behaviour is required from a commitment, assign very large
penalty prices, but we prefer modelling non-negotiable limits as Pyomo constraints.

Commitments are grouping across time and devices:

- ``_type == 'each'``: penalise deviations per time slot (default for time series).
- ``_type == 'any'``: treat the whole commitment horizon as one group (useful
  for peak-style penalties where only the maximum over the window should be
  counted).

.. note::

   Near-term feature: support for **grouping over devices** is planned and
   documented here. When enabled, grouping over devices lets you express
   soft constraints that aggregate deviations across a set of devices,
   for example, an intermediate capacity constraint from a feeder shared by a group of devices (via **flow commitments**), or multiple power-to-heat devices that feed a shared thermal buffer (via **stock commitments**).


How flex-context fields are converted into commitments
--------------------------------------------------------

Users may supply preferences and price fields in the ``flex-context``. The
scheduler then translates the relevant fields into one or more `Commitment` objects
before calling the optimizer.

Typical translations include:

- tariffs (``consumption-price``, ``production-price``) → an ``"energy"`` FlowCommitment with zero baseline so net consumption/production is priced;
- peak/excess limits (``site-peak-production``, ``site-peak-production-price``, etc.) → dedicated peak FlowCommitment(s);
- storage-related fields (``soc-minima``, ``soc-minima-breach-price``, etc.) → StockCommitment(s).


Let us look at some concrete examples. 
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


How you can use commitments for custom purposes: an example
------------------------------------------------------------

Suppose a site is asked to stay under a 500 kW maximum import capacity from 4 to 9 PM, and exceeding this triggers a penalty.
Then you could add this to the ``flex-context`` field of the site asset:

.. code-block:: json

    {
      "commitments": [
        {
          "name": "congestion pricing",
          "baseline": [
            {"value": "500 kW", "start": "2026-02-01T16:00:00+01:00", "end": "2026-02-01T21:00:00+01:00"}
          ],
          "up-price": "250 EUR/MW",
          "down-price": "0 EUR/MW",
        }
      ]
    }


The scheduler then takes into account that exceeding 500 kW consumption during the congested period will lead to additional costs of 0.25 EUR for every kW it goes over the limit.

.. note::

    The ``"commitments"`` field in the ``flex-context`` of an asset is not yet supported to be edited in the flex-context editor in the UI.
    Once it is, you will be able to use fixed quantities or sensors (for the baseline, up-price and down-price) to store custom commitments in the database.
    Passing the ``"commitments"`` field in the API call for schedule triggering is already supported (and probably preferrable for one-off commitments like the example above).
    And you can also use the FlexMeasures-Client to edit the ``flex-context`` on the asset level.

Advanced: mathematical formulation
----------------------------------

For a compact formulation of how commitments enter the optimization problem, see :ref:`storage_device_scheduler`.
