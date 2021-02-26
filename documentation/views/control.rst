.. _control:

*****************
Flexibility actions
*****************

Flexibility actions have commercial value that users can valorise on.
In the Flexibility actions page, FlexMeasures shows all flexibility actions that the user can take for a selected time window.
When FlexMeasures has identified commercial value for flexibility actions, the user is suggested to order them.
The user can opt to automate this otherwise manual process.
Listed flexibility actions include previously ordered actions and currently offered actions.
Currently offered actions are presented as an order book, where they are sorted according to their commercial value.
The user can place orders and check the expected value of offers.

.. contents::
    :local:
    :depth: 1


.. _action_types:

Types of flexibility actions
==========================

The platform distinguishes between different types of flexibility actions that an asset can take.

Curtailment
-----------

Curtailment happens when an asset temporarily lowers or stops its production or consumption.
A defining feature of curtailment is that total production or consumption at the end of the flexibility action has decreased.

- A typical example of curtailing production is when a wind turbine adjusts the pitch angle of its blades to decrease the generator torque.
- An example of curtailing consumption is load shedding of energy intensive industries.

Curtailment offers may specify some freedom in terms of how much energy can be curtailed.
In these cases, the user can select the energy volume (in MWh) to be ordered, within constraints set by the relevant Prosumer.
The net effect of a curtailment action is also measured in terms of an energy volume (see the flexibility metrics in the :ref:`portfolio` page).
Note that the volume ordered is not necessarily equal to the volume curtailed:
the ordered volume relates only to the selected time window,
while the curtailed volume may include volumes outside of the selected time window.
For example, an asset that runs an all-or-nothing consumption process of 2 hours can be ordered to curtail consumption for 1 hour, but will in effect stop the entire process.
In this case, the curtailed volume will be higher than the ordered volume, and the platform will take into account the total expected curtailment in its calculations.

Shifting
--------

Shifting happens when an asset delays or advances its energy production or consumption.
A defining feature of shifting is that total production or consumption at the end of the flexibility action remains the same.

- An example of delaying consumption is when a charging station postpones the charging process of an electric vehicle.
- An example of advancing consumption is when a cooling unit starts to cool before the upper temperature bound was reached (pre-cooling).

Shifting offers may specify some freedom in terms of how much energy can be shifted.
In these cases, the user can select the energy volume (in MWh) to be ordered, within constraints set by the relevant Prosumer.
This energy volume represents how much energy is shifting into or out of the selected time window.
The net effect of a shifting action is measured in terms of an energy-time volume (see the flexibility metrics in the :ref:`portfolio` page).
This volume is a multiplication of the energy volume being shifted and the duration of that shift.


Visualisation of actions
========================

Flexibility actions cause changes to the power profile of an asset.
Depending on the time window selection and constraints set by the asset owner, the effects of an action may partially take place outside of the selected time window.
Such effects are taken into account by FlexMeasures and shown to the user, e.g. as a part of expected value calculations and power profile forecasts.


.. image:: ../img/screenshot_control.png
    :target: ../../../../../../control
    :align: center
..    :scale: 40%
