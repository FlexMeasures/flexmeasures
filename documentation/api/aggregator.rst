.. _aggregator:

Aggregator
==========

The Aggregator organises the interaction between the Supplier and Prosumers/ESCos.

An Aggregator can access the following services:

- *postPrognosis* :ref:`(example) <post_prognosis_aggregator>`
- *postPriceData* :ref:`(example) <post_price_data_aggregator>`
- *getFlexRequest*
- *postFlexOffer*
- *getFlexOrder*
- *getMeterData* :ref:`(example) <get_meter_data_aggregator>`
- *getPrognosis* :ref:`(example) <get_prognosis_aggregator>`
- *getUdiEvent*
- *postDeviceMessage*

.. _post_prognosis_aggregator:

Post prognosis
--------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_prognosis

.. _post_price_data_aggregator:

Post price data
---------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_price_data


..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_flex_request

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_flex_offer

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_flex_order

.. _get_meter_data_aggregator:

Get meter data
--------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_meter_data

.. _get_prognosis_aggregator:

Get prognosis
-------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_prognosis

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.get_udi_event

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_device_message
