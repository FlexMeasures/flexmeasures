.. _prosumer:

Prosumer
========

A Prosumer owns a number of energy consuming or producing assets behind a connection to the electricity grid.

A Prosumer can access the following services:

- *postMeterData* :ref:`(example) <post_meter_data_prosumer>`
- *postPrognosis* :ref:`(example) <post_prognosis_prosumer>`
- *getMeterData* :ref:`(example) <get_meter_data_prosumer>`
- *getPrognosis* :ref:`(example) <get_prognosis_prosumer>`
- *postUdiEvent* :ref:`(example) <post_udi_event_prosumer>`
- *getDeviceMessage* :ref:`(example) <get_device_message_prosumer>`

.. _post_meter_data_prosumer:

Post meter data
---------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_meter_data

.. _post_prognosis_prosumer:

Post prognosis
--------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_prognosis

.. _get_meter_data_prosumer:

Get meter data
--------------

A Prosumer can query the FlexMeasures web service for its own meter data using the *getMeterData* service.

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_meter_data

.. _get_prognosis_prosumer:

Get prognosis
-------------

A Prosumer can query the FlexMeasures web service for prognoses of its own meter data using the *getPrognosis* service.

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_prognosis

.. _post_udi_event_prosumer:

Post UDI event
--------------

A Prosumer can post its flexibility constraints to the FlexMeasures web service as UDI events using the *postUdiEvent* service.

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_2.post_udi_event

.. _get_device_message_prosumer:

Get device message
------------------

A Prosumer can query the FlexMeasures web service for control signals using the *getDeviceMessage* service.

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_2.get_device_message
