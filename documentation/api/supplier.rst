.. _supplier:

Supplier
========

For the BVP, the Supplier represents the balance responsible party that request flexibility from asset owners.

A Supplier can access the following services:

- *getPrognosis* :ref:`(example) <get_prognosis>`
- *postFlexRequest*
- *getFlexOffer*
- *postFlexOrder*

.. _get_prognosis:

Get prognosis
-------------

.. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_prognosis

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_flex_request

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.get_flex_offer

..  .. autoflask:: bvp.app:create()
    :endpoints: bvp_api_v1_1.post_flex_order
