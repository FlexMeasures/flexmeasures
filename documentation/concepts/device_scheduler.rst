.. _storage_device_scheduler:

Device scheduler: mixed-integer linear model
=============================================

Introduction
--------------
This generic device scheduler is able to handle a site with multiple devices, with various types of constraints on the site level and on the device level,
and with multiple market commitments on the site level.

A typical example is a house with many devices. The commitments are assumed to be with regard to the flow of energy to the device (positive for consumption, negative for production). In practice, this generic scheduler is used in the **StorageScheduler** to schedule a storage device.

The solver minimizes the costs of deviating from the commitments.
For a more detailed explanation of commitments in FlexMeasures, see :ref:`commitments`.

The model is a *mixed-integer* linear program: binary variables model the sign of a device's power, the direction of a commitment deviation (only when the cost curve is non-convex), and the choice of operation mode for devices with power bands.
Without any of these, the model reduces to a plain linear program.

.. note::
    The model below is built by ``flexmeasures.data.models.planning.linear_optimization.device_scheduler`` using Pyomo.
    A second backend, ``flexmeasures.data.models.planning.highspy_optimization.device_scheduler_highspy``,
    builds the same model directly with the HiGHS Python API, which is much faster to construct.
    Both are fed by the same input preparation step, ``flexmeasures.data.models.planning.scheduling_problem.prepare_scheduling_problem``,
    and the symbols below refer to its output.


Notation
---------

Indexes
^^^^^^^^
=========  ====================  ===========================================================================================================================================================
Symbol     Variable in the Code  Description
=========  ====================  ===========================================================================================================================================================
:math:`c`  c                     Sub-commitments: one per commitment group, and one per deviation direction where a group spans several time steps (see `Commitments and sub-commitments`_).
:math:`d`  d                     Devices, for example, a battery or a load.
:math:`j`  j                     0-indexed time dimension.
:math:`g`  cg, cjg               Device groups within a device-scoped commitment :math:`c`.
:math:`s`  sg                    Stock groups: sets of devices that share one stock (e.g. one state-of-charge sensor).
:math:`e`  eg                    EMS constraint groups: sets of devices sharing one site-level capacity constraint (one per commodity).
:math:`b`  db                    Power bands (S2 operation modes) of a banded device :math:`d`.
:math:`k`  coupling_group_range  Coupling groups: sets of devices whose flows are hard-coupled in fixed proportions.
:math:`n`  balance_group_range   Balance groups: internal commodity nodes (e.g. a heat or steam network) whose flows must net to zero.
=========  ====================  ===========================================================================================================================================================

.. note::
  The time index :math:`j` has two interpretations: a time period or an instantaneous moment at the end of time period :math:`j`.
  For example, :math:`j` in flow constraints correspond to time periods, whereas :math:`j` used in a stock constraint refers to the end of time period :math:`j`.

Sets and mappings
^^^^^^^^^^^^^^^^^^

The constraints below sum over the devices that a group covers. These sets name those memberships.

======================  ============================  ==============================================================================================================
Symbol                  Variable in the Code          Description
======================  ============================  ==============================================================================================================
:math:`s(d)`            device_to_group               The stock group that device :math:`d` belongs to (its primary one, if it participates in several).
:math:`S(s)`            group_to_devices              The devices that share stock group :math:`s`. Written as :math:`d \in s` below.
:math:`E(e)`            ems_constraint_device_groups  The devices covered by EMS constraint group :math:`e`.
:math:`\mathcal{D}(c)`  commodity_devices             The devices covered by an EMS-level commitment :math:`c`: all devices, or those of the commitment's commodity.
:math:`G(c,g)`          device_group_lookup           The devices in device group :math:`g` of a device-scoped commitment :math:`c`.
:math:`N(n)`            balance_group_specs           The devices attached to internal commodity node :math:`n`.
======================  ============================  ==============================================================================================================

Parameters
^^^^^^^^^^
==========================================  =================================  ========================================================================================================================================
Symbol                                      Variable in the Code               Description
==========================================  =================================  ========================================================================================================================================
:math:`Price_{up}(c)`                       up_price                           Price of incurring an upwards deviation in sub-commitment :math:`c`.
:math:`Price_{down}(c)`                     down_price                         Price of incurring a downwards deviation in sub-commitment :math:`c`.
:math:`Commitment(c,j)`                     commitment_quantity                Committed quantity of sub-commitment :math:`c` for time period :math:`j` (a flow, or a stock for stock commitments).
:math:`\eta_{up}(d,j)`                      device_derivative_up_efficiency    Upwards conversion efficiency (stock increase : flow in).
:math:`\eta_{down}(d,j)`                    device_derivative_down_efficiency  Downwards conversion efficiency (flow out : stock decrease).
:math:`Stock_{min}(d,j)`                    device_min                         Minimum stock of device :math:`d` at the end of time period :math:`j`, relative to its initial stock.
:math:`Stock_{max}(d,j)`                    device_max                         Maximum stock of device :math:`d` at the end of time period :math:`j`, relative to its initial stock.
:math:`Stock_0(d)`                          initial_stock                      Initial stock of device :math:`d`, shared by all devices in its stock group.
:math:`\epsilon(d,j)`                       device_efficiency                  Storage efficiency (stock losses), shared by all devices in a stock group.
:math:`P_{max}(d,j)`                        device_derivative_max              Maximum flow of device :math:`d` during time period :math:`j`.
:math:`P_{min}(d,j)`                        device_derivative_min              Minimum flow of device :math:`d` during time period :math:`j`.
:math:`P^{ems}_{min}(e,j)`                  ems_derivative_min                 Minimum aggregated flow of EMS constraint group :math:`e` during time period :math:`j`.
:math:`P^{ems}_{max}(e,j)`                  ems_derivative_max                 Maximum aggregated flow of EMS constraint group :math:`e` during time period :math:`j`.
:math:`D(d,j)`                              stock_delta                        Explicit stock gain or loss of device :math:`d` during time period :math:`j`.
:math:`\gamma(k,d)`                         coupling_device_specs              Fixed proportion of device :math:`d` within coupling group :math:`k`. Positive for inputs (consuming), negative for outputs (producing).
:math:`B_{min}(d,b)`, :math:`B_{max}(d,b)`  band_lookup                        Lower and upper flow bound of power band :math:`b` of device :math:`d`.
:math:`M_d`                                 Md                                 Big-M bounding device power: the largest absolute device flow limit (at least 1 MW).
:math:`M_c`                                 Mc                                 Big-M bounding commitment deviations: the summed absolute device flow limits (at least 1 MW).
==========================================  =================================  ========================================================================================================================================


Variables
^^^^^^^^^
=========================  ==============================  =====================================================================================================================
Symbol                     Variable in the Code            Description
=========================  ==============================  =====================================================================================================================
:math:`\Delta_{up}(c)`     commitment_upwards_deviation    Upwards deviation from sub-commitment :math:`c` (:math:`\geq 0`). One variable per sub-commitment, not per time step.
:math:`\Delta_{down}(c)`   commitment_downwards_deviation  Downwards deviation from sub-commitment :math:`c` (:math:`\leq 0`).
:math:`\sigma_c(c)`        commitment_sign                 Binary. Upwards deviation allowed if :math:`\sigma_c(c)=1`, downwards deviation otherwise.
:math:`P_{up}(d,j)`        device_power_up                 Upwards (consuming) power of device :math:`d` during time period :math:`j` (:math:`\geq 0`).
:math:`P_{down}(d,j)`      device_power_down               Downwards (producing) power of device :math:`d` during time period :math:`j` (:math:`\leq 0`).
:math:`P^{ems}(d,j)`       ems_power                       Net flow of device :math:`d` during time period :math:`j`.
:math:`\sigma(d,j)`        device_power_sign               Binary. Upwards power activation if :math:`\sigma(d,j)=1`, downwards power activation otherwise.
:math:`Stock(s,j)`         group_stock                     Stock of stock group :math:`s` at the end of time period :math:`j`.
:math:`\Delta Stock(s,j)`  n/a                             Auxiliary symbol used below: the stock change of stock group :math:`s` during time period :math:`j`, before losses.
:math:`\alpha(k,j)`        coupling_alpha                  Common normalised flow level of coupling group :math:`k` during time period :math:`j`.
:math:`y(d,b,j)`           device_band                     Binary. Device :math:`d` operates in power band :math:`b` during time period :math:`j`.
=========================  ==============================  =====================================================================================================================

Commitments and sub-commitments
--------------------------------

A commitment may declare a ``group`` per time step, which defines the set of time steps within which deviations are accounted for together
(for example: only the highest breach per calendar month is penalised).
Before the model is built, every commitment is split into *sub-commitments*: one per group, and — where a group spans multiple time steps — one per deviation direction.
The index :math:`c` therefore runs over sub-commitments, and each carries a single pair of deviation prices.

This is why the deviation variables :math:`\Delta_{up}(c)` and :math:`\Delta_{down}(c)` are *not* indexed by time:
one deviation is paid for per sub-commitment, however many time steps it spans.
For the common case of a per-time-step commitment (such as an energy tariff), each time step forms its own group, and the two coincide.

After solving, the costs of the sub-commitments are aggregated back to the original commitments (``model.commitment_costs``) and per commodity (``model.commodity_costs``).

Cost function
--------------

The cost function quantifies the total cost of upwards and downwards deviations from the different sub-commitments.

.. math::
    :name: cost_function

    \min \sum_{c} [\Delta_{up}(c) \cdot Price_{up}(c) + \Delta_{down}(c) \cdot Price_{down}(c)]

Note that :math:`\Delta_{down}(c) \leq 0`, so a positive downwards deviation price yields a negative contribution, and vice versa.
This mirrors the sign convention described under :ref:`commitments`.


State dynamics
---------------

Stock is tracked per *stock group* :math:`s`: a set of devices that share one stock, such as several converters filling one buffer.
Devices that are not part of a declared stock group form a stock group of their own.
Because the stock is a property of the group, all its devices must declare the same storage efficiency and the same initial stock.

To simplify the description of the model, the auxiliary variable :math:`\Delta Stock(s,j)` is introduced in the documentation. It represents the
change of :math:`Stock(s,j)`, taking into account conversion efficiencies but not considering the storage losses.

.. math::
  :name: stock

    \Delta Stock(s,j) = \sum_{d \in s} \left[ \frac{P_{down}(d,j)}{\eta_{down}(d,j)} + P_{up}(d,j) \cdot \eta_{up}(d,j) + D(d,j) \right]

The stock is then defined recursively, rather than as a running sum over all preceding time steps, which keeps the number of nonzeros in the model linear (rather than quadratic) in the scheduling horizon:

.. math::
  :name: group_stock_balance

    Stock(s, j) = a(s,j) \cdot Stock(s, j-1) + b(s,j) \cdot \Delta Stock(s,j)

with :math:`Stock(s, -1) = Stock_0(d)` for any device :math:`d \in s` (the group's devices share one initial stock), and with the loss coefficients

.. math::
  :name: loss_coefficients

    (a(s,j), b(s,j)) = \begin{cases}
    (1, 1) & \text{if } \epsilon(d,j) = 1 \\
    \left(\epsilon(d,j), \frac{\epsilon(d,j) - 1}{\log(\epsilon(d,j))}\right) & \text{otherwise}
    \end{cases}

for any device :math:`d \in s` (they all share the group's storage efficiency).

.. note::
    This is the *linear* treatment of storage losses: the stock is assumed to change at a constant rate, while losses decay exponentially, within each time step.
    The scheduler models losses this way exclusively. The alternative treatments (perfect, left and right) still exist in
    ``flexmeasures.utils.calculations.apply_stock_changes_and_losses``, which reconstructs a stock series from a known power series.

Constraints
--------------

Device bounds
^^^^^^^^^^^^^

Stock bounds are expressed relative to the device's initial stock, and refer to the stock of the group the device belongs to:

.. math::
  :name: device_bounds

    Stock_{min}(d,j) \leq Stock(s(d), j) - Stock_0(d) \leq Stock_{max}(d,j)

.. math::
  :name: device_derivative_bounds

    P_{min}(d,j) \leq P_{up}(d,j) + P_{down}(d,j)\leq P_{max}(d,j)

.. math::
  :name: device_down_derivative_bounds

    min(P_{min}(d,j),0) \leq P_{down}(d,j)\leq 0


.. math::
  :name: device_up_derivative_bounds

    0 \leq P_{up}(d,j)\leq max(P_{max}(d,j),0)


Upwards/Downwards activation selection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Avoid simultaneous upwards and downwards activation during the same time period.

.. math::
  :name: device_up_derivative_sign

    P_{up}(d,j) \leq M_d \cdot \sigma(d,j)

.. math::
  :name: device_down_derivative_sign

    -P_{down}(d,j) \leq M_d \cdot (1-\sigma(d,j))

The same trick prevents a sub-commitment from deviating in both directions at once:

.. math::
  :name: commitment_up_derivative_sign

    \Delta_{up}(c) \leq M_c \cdot \sigma_c(c)

.. math::
  :name: commitment_down_derivative_sign

    -\Delta_{down}(c) \leq M_c \cdot (1-\sigma_c(c))

These two constraints are only added when the summed deviation prices do not describe a convex cost curve.
For a convex cost curve, deviating in both directions is never optimal anyway, so dropping them leaves the problem a pure LP.
The direct HiGHS backend then omits :math:`\sigma_c(c)` as well, while the Pyomo backend still declares the variable, leaving it unreferenced.

Grid constraints
^^^^^^^^^^^^^^^^^

.. math::
    :name: device_derivative_equalities

    P^{ems}(d,j) = P_{up}(d,j) + P_{down}(d,j)

Site-level capacity is enforced per EMS constraint group :math:`e`, over the devices :math:`E(e)` it covers.
The StorageScheduler uses one group per commodity, so each commodity gets its own site-level capacity constraint.
A single group covering all devices is the default (and the historical behaviour).

.. math::
  :name: ems_derivative_bounds

    P^{ems}_{min}(e,j) \leq \sum_{d \in E(e)} P^{ems}(d,j) \leq P^{ems}_{max}(e,j)

EMS-level commitments
^^^^^^^^^^^^^^^^^^^^^^

Commitments that do not name a device apply to the site as a whole.
Writing :math:`\mathcal{D}(c)` for the devices such a commitment covers — all devices, or, if the commitment names a commodity, the devices of that commodity — and

.. math::
    :name: ems_flow_commitment_deviation

    \Xi(c,j) = Commitment(c,j) + \Delta_{down}(c) + \Delta_{up}(c) - \sum_{d \in \mathcal{D}(c)} P^{ems}(d,j)

the constraint is bounded on the side(s) for which the sub-commitment carries a deviation price:

================================  =========================  =====================================================================
Sub-commitment prices             Constraint                 Meaning
================================  =========================  =====================================================================
Both prices given                 :math:`0 \leq \Xi \leq 0`  The commitment is met exactly, or paid for in both directions.
Only an upwards deviation price   :math:`\Xi \geq 0`         Flow above the committed quantity is a breach; staying below is free.
Only a downwards deviation price  :math:`\Xi \leq 0`         Flow below the committed quantity is a breach; staying above is free.
================================  =========================  =====================================================================

Device-scoped commitments
^^^^^^^^^^^^^^^^^^^^^^^^^^

A commitment may instead name devices, optionally organised in device groups :math:`g` (the ``device_group`` column; by default each device forms its own group).
It is then bound once per device group, against the aggregate of that group's devices :math:`G(c,g)`.
For a flow commitment, the aggregate is a flow:

.. math::
    :name: grouped_flow_commitment_deviation

    \Xi(c,j,g) = Commitment(c,j) + \Delta_{down}(c) + \Delta_{up}(c) - \sum_{d \in G(c,g)} P^{ems}(d,j)

and for a stock commitment, it is a stock change since the start of the schedule:

.. math::
    :name: grouped_stock_commitment_deviation

    \Xi(c,j,g) = Commitment(c,j) + \Delta_{down}(c) + \Delta_{up}(c) - \sum_{d \in G(c,g)} [Stock(s(d), j) - Stock_0(d)]

Both are bounded exactly as in the table above.
A stock commitment that names a stock group couples to that group as a whole, through a single representative device, so a shared stock is not counted more than once.

Hard flow coupling
^^^^^^^^^^^^^^^^^^^

Devices in a coupling group :math:`k` are forced to operate in fixed proportion to one another —
for example a CHP unit whose gas input, heat output and power output move together.
A free variable :math:`\alpha(k,j)` represents the group's common normalised flow level:

.. math::
    :name: flow_coupling

    P^{ems}(d,j) = \gamma(k,d) \cdot \alpha(k,j) \qquad \forall d \in k

Balance groups (internal commodity nodes)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

An internal commodity node — a heat or steam network without its own grid connection — stores nothing itself:
everything produced into the node must be consumed from it within the same time step.

.. math::
    :name: node_balance

    \sum_{d \in N(n)} P^{ems}(d,j) = 0

Derivative efficiencies and stock deltas describe each device's own stock-side conversion, and do not enter this commodity-side balance.
To give a node storage, include a storage device in the group: its flow absorbs the imbalance, while its stock is bounded by its own device constraints.

Power bands (S2 operation modes)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A device may declare a list of signed power bands, and must then operate within exactly one of them at every time step.
Which band it runs in is a free binary decision:

.. math::
    :name: device_band_choice

    \sum_{b} y(d,b,j) = 1

.. math::
    :name: device_band_power_bounds

    \sum_{b} y(d,b,j) \cdot B_{min}(d,b) \leq P_{up}(d,j) + P_{down}(d,j) \leq \sum_{b} y(d,b,j) \cdot B_{max}(d,b)

Because exactly one band binary is 1, each sum selects the bound of the chosen band.
Bands are what make a device's feasible operating region non-convex (for instance, "off, or between 40% and 100%"), at the cost of one binary variable per device per band per time step.
