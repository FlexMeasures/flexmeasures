.. _prosumer:

Prosumer
========

A Prosumer owns a number of energy consuming or producing assets behind a connection to the electricity grid.
A Prosumer can query the BVP web service for its own meter data using the *getMeterData* service.

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_meter_data
