.. _benefits_of_flex:

Benefits from energy flexibility
====================================

.. contents::
    :local:
    :depth: 1


Flexibility opportunities and activation
-----------------------------------------

In an energy system with flexible energy assets present (e.g. batteries, heating/cooling), there exist 
opportunities to activate such flexibility.

The opportunity lies in waiting with a planned comsumption or generation action ("shifting") or to
adapt an action ("curtailment"). 

Within FlexMeasures, this opportunity can be inspected as the difference between forecasts
(how the assets would act without activation of flexibility) and suggested schedules (the activation of flexibility).


Positive values indicate an increase in production or a decrease in consumption,
both of which result in an increased load on the network.

For short-term changes in power due to activation of flexibility, this is sometimes called up-regulation.
Negative values indicate a decrease in production or an increase in consumption,
which result in a decreased load on the network (down-regulation).

-----
Flexibility actions have commercial value that users can valorise on.


Profit sharing
---------------
There are different roles in a modern smart energy system (e.g. "Prosumer", "DSO", Aggregator", "ESCo"),
and they all enjoy the benefits of flexibility  in different ways
(see for example `this resource <https://www.usef.energy/role-specific-benefits/>`_ for more details).

In our opinion, the only way to successful implmentation of enegy flexbility is if profits 
are shared between these stakeholder. This assumes contractual relationships. Use cases which FlexMeasures 
can support well are relationships:

* between Aggregator and Prosumer, where the Aggregator sells the balancing power to a third party and shares the profits with the Prosumer according to some contracted method for profit sharing. In this case the stated costs and revenues for the Prosumer may be after deducting the Aggregator fee (which typically include price components per flex activation and price components per unit of time, but may include arbitrarily complex price components).
* between ESCo and Prosumer, where the ESCo advises the Prosumer to optimise against e.g. dynamic prices. Likewise, stated numbers may be after deducting the ESCo fee.

FlexMeaures can take these intricacies into account if a custom optimisation algorithm is plugged in to model them.

Alternatively, we can assume that all profit from activating flexibility goes to the Prosumer, or simply report the profits before sharing (and before deducting any service fees).

The realisation of payments is outside of FlexMeasures scope, but it provides the accounting to enable them.