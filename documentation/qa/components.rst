.. _components:

****************************************
What components does the BVP consist of?
****************************************


.. image:: ../img/components.png
    :align: center
..    :scale: 40%


Legend

.. image:: ../img/legend.png
    :align: center
..    :scale: 10% 



Platform components
===================


Trade controller
----------------

Trading logic and trading UI for Supplier.


DR controller
-------------

Broker logic and broker UI for Aggregator.


Resource controller
-------------------

Planning logic and planning UI for Prosumer.


External components
===================


A1 simulator
------------

The platform is coupled to the A1 power systems simulator.
This simulator provides price data from the Korean Power Exchange (KPX) and consumption/production data from assets on Jeju island.


.. _weather:

Weather service
---------------

The platform is coupled to the Darksky weather service.

