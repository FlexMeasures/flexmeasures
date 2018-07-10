.. _aggregator:

Aggregator
==========

The Aggregator organises the interaction between the Supplier and Prosumers/ESCos.

An Aggregator can access the following services:

- *postPrognosis*
- *getFlexRequest*
- *postFlexOffer*
- *getFlexOrder*
- *getMeterData* :ref:`(example) <get_meter_data>`
- *getPrognosis* :ref:`(example) <get_prognosis>`
- *getUdiEvent*
- *postDeviceMessage*

.. .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_prognosis

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_flex_request

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_flex_offer

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_flex_order

.. _get_meter_data:

Get meter data
--------------

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_meter_data

.. _get_prognosis:

Get prognosis
-------------

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_prognosis

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_udi_event

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_device_message
