.. _benefits_of_flex:

Benefits from energy flexibility
====================================

FlexMeasures was created so that the value of energy flexibility can be realised.
This will make energy cheaper to use, and can also reduce CO₂ emissions.
Here, we define a few terms around this idea, which come up in other parts of this documentation.

.. contents::
    :local:
    :depth: 2


Flexibility opportunities and their activation
-----------------------------------------

In an energy system with flexible energy assets present (e.g. batteries, heating/cooling), there exist 
opportunities to activate such flexibility.

The opportunity lies in waiting with a planned consumption or generation action ("shifting") or to
adapt an action ("curtailment") ― see :ref:`opportunity_types` for a deeper discussion. Often, such opportunities are discussed under the label "demand response".

Within FlexMeasures, this opportunity can be regarded as the difference between suggested schedules (the activation of flexibility) and forecasts (how the assets are expected to act without activation of flexibility).

What does it mean to activate flexibility from such an opportunity?

Positive values in the aforementioned differences indicate an increase in production or a decrease in consumption on activation, both of which result in an increased grid frequency.
For short-term changes in power due to activation of flexibility opportunities, this is sometimes called `"up-regulation"`.

On the other hand, negative values indicate a decrease in production or an increase in consumption,
which result in a decreased grid frequency (`"down-regulation"`).

Finally, flexibility activations have commercial value that users can valorise on. This value can fall to the platform operator or be shared among stakeholders. We talk more about this in :ref:`activation_profits`.


.. _opportunity_types:

Types of flexibility opportunities
--------------------------------------

The FlexMeasures platform distinguishes between different types of flexibility opportunities and the type of action to take advantage of it. We explain them in more detail, together with examples.


Curtailment
^^^^^^^^^^^^^^

Curtailment happens when an asset temporarily lowers or stops its production or consumption.
A defining feature of curtailment is that total production or consumption at the end of the flexibility opportunity has decreased.

- A typical example of curtailing production is when a wind turbine adjusts the pitch angle of its blades to decrease the generator torque.
- An example of curtailing consumption is load shedding of energy intensive industries.

Curtailment offers may specify some freedom in terms of how much energy can be curtailed.
In these cases, the user can select the energy volume (in MWh) to be ordered, within constraints set by the relevant Prosumer.
The net effect of a curtailment action is also measured in terms of an energy volume (see the flexibility metrics in the :ref:`portfolio` page).

Note that the volume ordered is not necessarily equal to the volume curtailed:
the ordered volume relates only to the selected time window, while the curtailed volume may include volumes outside of the selected time window.
For example, an asset that runs an all-or-nothing consumption process of 2 hours can be ordered to curtail consumption for 1 hour, but will in effect stop the entire process.
In this case, the curtailed volume will be higher than the ordered volume, and the platform will take into account the total expected curtailment in its calculations.

Shifting
^^^^^^^^^^^^^^

Shifting happens when an asset delays or advances its energy production or consumption.
A defining feature of shifting is that total production or consumption at the end of the flexibility opportunity remains the same.

- An example of delaying consumption is when a charging station postpones the charging process of an electric vehicle.
- An example of advancing consumption is when a cooling unit starts to cool before the upper temperature bound was reached (pre-cooling).

Shifting offers may specify some freedom in terms of how much energy can be shifted.
In these cases, the user can select the energy volume (in MWh) to be ordered, within constraints set by the relevant Prosumer.
This energy volume represents how much energy is shifting into or out of the selected time window.
The net effect of a shifting action is measured in terms of an energy-time volume (see the flexibility metrics in the :ref:`portfolio` page).
This volume is a multiplication of the energy volume being shifted and the duration of that shift.


.. _activation_profits:

Profits of flexibility activation
---------------

The realised value from activating flexibility opportunities has to be computed and accounted for.
Both of these activities depend on the context in which FlexMeasures is being used, and we expect that it will be often have to implemented in a custom manner (much as the actual scheduling optimization).

.. note:: Making it possible to configure custom scheduling and value accounting is on the roadmap for FlexMeasures.

Computing value
^^^^^^^^^^^^^^^^

The computation of the value is what drives the scheduling optimization. This value is usually monetary, and in that case there should be some form of market configured. This can be a constant or time-of-use tariff, or a real market. However, there are other possibilities, for instance if the optimisation goal is to minimise the CO₂ consumption. The realised value is avoided CO₂, whcih is probably not easy to translate into a monetary value.


Accounting / Sharing value
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The realisation of payments is outside of FlexMeasures scope, but it can provide the accounting to enable them (as was said above, this is usually a part of the optimisation problem formulation).

However, next to fueling algorithmic optimization, the value of energy flexibility also drives project participation. Accounting plays an important role here.

There are different roles in a modern smart energy system (e.g. "Prosumer", "DSO", Aggregator", "ESCo"),
and they all enjoy the benefits of flexibility  in different ways
(see for example `this resource <https://www.usef.energy/role-specific-benefits/>`_ for more details).

In our opinion, the only way to successful implementation of energy flexibility is if profits
are shared between these stakeholders. This assumes contractual relationships. Use cases which FlexMeasures 
can support well are the following relationships:

* between Aggregator and Prosumer, where the Aggregator sells the balancing power to a third party and shares the profits with the Prosumer according to some contracted method for profit sharing. In this case the stated costs and revenues for the Prosumer may be after deducting the Aggregator fee (which typically include price components per flex activation and price components per unit of time, but may include arbitrarily complex price components).

* between ESCo and Prosumer, where the ESCo advises the Prosumer to optimise against e.g. dynamic prices. Likewise, stated numbers may be after deducting the ESCo fee.

FlexMeasures can take these intricacies into account if a custom optimisation algorithm is plugged in to model them.

Alternatively, we can assume that all profit from activating flexibility goes to the Prosumer, or simply report the profits before sharing (and before deducting any service fees).
