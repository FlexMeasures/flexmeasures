.. _benefits_of_flex:

Energy flexibility
=====================

FlexMeasures was created so that the value of energy flexibility can be realized.
This will make energy cheaper to use, and can also reduce CO₂ emissions.
Here, we define a few terms around this idea, which come up in other parts of this documentation.

.. contents::
    :local:
    :depth: 2


Behind-the-meter and front-of-the-meter
----------------------------------------

In the energy sector, we draw a distinction between behind-the-meter (BTM) and front-of-the-meter (FTM) optimization. As usual, the distinction isn't always clear, but we can give the general definition and the focus for FlexMeasures (BTM).

BTM optimization describes the optimization of assets connected on a site behind the main meter (which has the connection to the rest of the electricity grid). Think of local solar, heating, EV charging and even batteries. A (dynamic) tariff and limits to the grid connection often complete the picture, which can become quite complex and also rewarding to get right.

On the other hand, there is front-of-the-meter (FTM) optimization, which relates to grid-level optimization as is the work of utilities, DSOs and TSOs. Think of large-scale generation and its role in wholesale markets, managing transmission lines. But also, flexible grid-level assets like batteries and solar parks might belong here, and you might find that FlexMeasures can help to optimize some of these assets if you model the circumstances correctly.

When we focus on the situation behind the meter, do we ignore everything else? Not at all. It simply means to prioritize the local orchestration modeling, and then add services which the site can offer to the grid. For instance, using a dynamic tariff can already help the grid. Obeying (flexible) grid capacity constraints, as well, of course. Going further, extra flexibility can be offered explicitly to congestion markets/auctions, which is part of `FlexMeasures' roadmap <https://flexmeasures.io/roadmap/>`_. (Note: For a distinction between implicit and explicit flexibility, read on below).


Flexibility opportunities and activation
-----------------------------------------

Opportunities
^^^^^^^^^^^^^^

In an energy system with flexible energy assets present (e.g. batteries, heating/cooling), there are
opportunities to profit from the availability and activation of their flexibility.

Energy flexibility can come from the ability to store energy ("storage"), to delay (or advance) planned consumption or production ("shifting"), the ability to lower production ("curtailment"), or the ability to increase or decrease consumption ("demand response") ― see :ref:`flexibility_types` for a deeper discussion.

Under a given incentive, this flexibility represents an opportunity to profit by scheduling consumption or production differently than originally planned.
Within FlexMeasures, flexibility is represented as the difference between a suggested schedule and a given baseline.
By default, a baseline is determined by our own forecasts.

Opportunities are expressed with respect to given economical and ecological incentives.
For example, a suggested schedule may represent an opportunity to save X EUR and Y tonnes of CO₂.

Activation
^^^^^^^^^^^^^^^

The activation of flexibility usually happens in a context of incentives. Often, that context is a market.
We recommend `the USEF white paper on the flexibility value chain <https://www.usef.energy/app/uploads/2018/11/USEF-White-paper-Flexibility-Value-Chain-2018-version-1.0_Oct18.pdf>`_ for an excellent introduction of who can benefit from energy flexibility and how it can be delivered.
The high-level takeaways are these:

- the value of flexibility flows back to Prosumers along a chain of roles involved in the activation of their flexibility: the **Flexibility Value Chain**.
- a portfolio of flexible assets (and even individual assets) may provide services in multiple contexts in the same period: **value stacking**.
- **Explicit demand-side flexibility** services involve Aggregators, while **implicit demand-side flexibility** services involve Energy Service Companies (ESCos).
- Many remuneration components for flexibility services requires the determination of a baseline according to some **baseline methodology**.
- Both availability and activation of flexibility have value.

The overall value (from availability and activation of flexibility), and how this value is shared amongst stakeholders in the various roles in the Flexibility Value Chain, can be accounted for by the platform operator.
We talk more about this in :ref:`activation_profits`.


An example: the balancing market
----------------------------------------
An example of a market on which flexibility can be activated is the balancing market, which is meant to bring the grid frequency back to a target level within a matter of minutes.
Consider the aforementioned differences between suggested schedules and a given baseline.
In the context of the balancing market, differences indicating an increase in production or a decrease in consumption on activation both result in an increasing grid frequency (back towards the target frequency).

The balancing market pays for such services, and they are often referred to as `"up-regulation"`.
It works the other way around, too: differences indicating a decrease in production or an increase in consumption both result in a decreasing grid frequency (`"down-regulation"`).


.. _flexibility_types:

Types of flexibility
--------------------------------------

The FlexMeasures platform distinguishes between different types of flexibility. We explain them here in more detail, together with examples.


Curtailment
^^^^^^^^^^^^^^

Curtailment happens when an asset temporarily lowers or stops its production or consumption.
A defining feature of curtailment is that total production or consumption decreases when this this flexibility is activated.

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
A defining feature of shifting is that total production or consumption remains the same when this flexibility is activated.

- An example of delaying consumption is when a charging station postpones the charging process of an electric vehicle.
- An example of advancing consumption is when a cooling unit starts to cool before the upper temperature bound was reached (pre-cooling).

Shifting offers may specify some freedom in terms of how much energy can be shifted.
In these cases, the user can select the energy volume (in MWh) to be ordered, within constraints set by the relevant Prosumer.
This energy volume represents how much energy is shifting into or out of the selected time window.
The net effect of a shifting action is measured in terms of an energy-time volume (see the flexibility metrics in the :ref:`portfolio` page).
This volume is a multiplication of the energy volume being shifted and the duration of that shift.


.. _activation_profits:

Profits of flexibility activation
---------------------------------

The realized value from activating flexibility has to be computed and accounted for.
Both of these activities depend on the context in which FlexMeasures is being used, and we expect that it will often have to be implemented in a custom manner (much as the actual scheduling optimization).

.. todo:: Making it possible to configure custom scheduling and value accounting is on the roadmap for FlexMeasures.

Computing value
^^^^^^^^^^^^^^^^

The computation of the value is what drives the scheduling optimization.
This value is usually monetary, and in that case there should be some form of market configured.
This can be a constant or time-of-use tariff, or a real market.
However, there are other possibilities, for instance if the optimization goal is to minimize CO₂ emissions.
Then, the realized value is avoided CO₂, which nowadays has an assumed value, e.g. in `the EU ETS carbon market <https://ember-climate.org/data/carbon-price-viewer/>`_.


Accounting / Sharing value
^^^^^^^^^^^^^^^^^^^^^^^^^^^

The realization of payments is outside of the scope of FlexMeasures, but it can provide the accounting to enable them (as was said above, this is usually a part of the optimization problem formulation).

However, next to fueling algorithmic optimization, the way that the value of energy flexibility is shared among the stakeholders will also be an important driver for project participation. Accounting plays an important role here.

There are different roles in a modern smart energy system (e.g. "Prosumer", "DSO", Aggregator", "ESCo"),
and they all enjoy the benefits of flexibility  in different ways
(see for example `this resource <https://www.usef.energy/role-specific-benefits/>`_ for more details).

In our opinion, the only way to successful implementation of energy flexibility is if profits
are shared between these stakeholders. This assumes contractual relationships. Use cases which FlexMeasures 
can support well are the following relationships:

* between Aggregator and Prosumer, where the Aggregator sells the balancing power to a third party and shares the profits with the Prosumer according to some contracted method for profit sharing. In this case the stated costs and revenues for the Prosumer may be after deducting the Aggregator fee (which typically include price components per flex activation and price components per unit of time, but may include arbitrarily complex price components).

* between ESCo and Prosumer, where the ESCo advises the Prosumer to optimize against e.g. dynamic prices. Likewise, stated numbers may be after deducting the ESCo fee.

FlexMeasures can take these intricacies into account if a custom optimization algorithm is plugged in to model them.

Alternatively, we can assume that all profit from activating flexibility goes to the Prosumer, or simply report the profits before sharing (and before deducting any service fees).


A word on terminology
----------------------------

FlexMeasures is compliant with the `Universal Smart Energy Framework (USEF) <https://www.usef.energy/>`_.
Therefore, this documentation uses USEF terminology, e.g. for role definitions.
In this context, the intended users of FlexMeasures are a Supplier (energy company) and its Prosumers (asset owners who have energy contracts with that Supplier).
The platform operator of FlexMeasures can be an Aggregator.