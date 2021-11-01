.. _auth-dev:

Custom authorization
======================

Our :ref:`auth` section describes general authentication and authorization handling in FlexMeasures. However, custom energy flexibility services developed on top of FlexMeasures probably also need their custom authorization. 

One means for this is to define custom account roles. E.g. if several services run on one FlexMeasures server, each service could define a "MyService-subscriber" account role. To make sure that only users of such accounts can use the endpoints:

.. code-block:: python

    @flexmeasures_ui.route("/bananas")
    @account_roles_required("MyService-subscriber")
    def bananas_view:
        pass

.. note:: This endpoint decorator lists required roles, so the authenticated user's account needs to have each role. You can also use the ``account_roles_accepted`` decorator. Then the user's account only needs to have at least one of the roles.

There are also decorators to check user roles:

.. code-block:: python 

    @flexmeasures_ui.route("/bananas")
    @roles_required("account-admin")
    def bananas_view:
        pass

.. note:: You can also use the ``roles_accepted`` decorator.

