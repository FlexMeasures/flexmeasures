.. _prosumer:

Prosumer
========

A Prosumer owns a number of energy consuming or producing assets behind a connection to the electricity grid.

A Prosumer can access the following services:

- *postMeterData* :ref:`(example) <post_meter_data_prosumer>`
- *postPrognosis* :ref:`(example) <post_prognosis_prosumer>`
- *getMeterData* :ref:`(example) <get_meter_data_prosumer>`
- *getPrognosis* :ref:`(example) <get_prognosis_prosumer>`
- *postUdiEvent*
- *getDeviceMessage*

.. _post_meter_data_prosumer:

Post meter data
---------------

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_meter_data

.. _post_prognosis_prosumer:

Post prognosis
--------------

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_prognosis

.. _get_meter_data_prosumer:

Get meter data
--------------

A Prosumer can query the BVP web service for its own meter data using the *getMeterData* service.

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_meter_data

.. _get_prognosis_prosumer:

Get prognosis
-------------

A Prosumer can query the BVP web service for prognoses of its own meter data using the *getPrognosis* service.

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_prognosis
