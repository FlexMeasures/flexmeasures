.. _supplier:

Supplier
========

For FlexMeasures, the Supplier represents the balance responsible party that request flexibility from asset owners.

A Supplier can access the following services:

- *getPrognosis* :ref:`(example) <get_prognosis_supplier>`
- *postPriceData* :ref:`(example) <post_price_data_supplier>`
- *postFlexRequest*
- *getFlexOffer*
- *postFlexOrder*

.. _get_prognosis_supplier:

Get prognosis
-------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures.api_v1_1.get_prognosis

.. _post_price_data_supplier:

Post price data
---------------

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures.api_v1_1.post_price_data

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures.api_v1_1.post_flex_request

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures.api_v1_1.get_flex_offer

..  .. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures.api_v1_1.post_flex_order
