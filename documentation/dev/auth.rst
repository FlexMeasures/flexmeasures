.. _auth-dev:

Custom authorization
======================

Our :ref:`authorization` section describes general authorization handling in FlexMeasures.

If you are creating your own API endpoints for a custom energy flexibility services (on top of FlexMeasures), you should also get your authorization right. 
It's recommended to get familiar with the decorators we provide. Here are some pointers, but feel free to read more in the ``flexmeasures.auth`` package. 

In short, we recommend to use the ``@permission_required_for_context`` decorator (more explanation below).

FlexMeasures also supports role-based decorators, e.g. ``@account_roles_required``. These authorization decorators are straightforward. However, they are a bit crude as they do not qualify on the permission (e.g. read versus write). A consequence of this is that the ``admin-reader`` role cannot be checked in role-based decorators.

Finally, all decorators available through `Flask-Security-Too <https://flask-security-too.readthedocs.io/en/stable/patterns.html#authentication-and-authorization>`_ can be used, e.g. ``@auth_required`` (that's technically only checking authentication) or ``@permissions_required``.


Permission-based authorization
--------------------------------

Via permissions, it's possible to define authorization access to data, distinguishing between create, read, update and delete access. It's a finer model than simply allowing per role.

The data models codify under which conditions a user can have certain permissions to work with their data.
You, as the endpoint author, need to make sure this is checked. Here is an example (taken from the decorator docstring):

.. code-block:: python

    @app.route("/resource/<resource_id>", methods=["GET"])
    @use_kwargs(
        {"the_resource": ResourceIdField(data_key="resource_id")},
        location="path",
    )
    @permission_required_for_context("read", arg_name="the_resource")
    @as_json
    def view(resource_id: int, resource: Resource):
        return dict(name=resource.name)

As you see, there is some sorcery with ``@use_kwargs`` going on before we check the permissions. `That decorator <https://webargs.readthedocs.io>`_ is relaying to a `Marshmallow <https://marshmallow.readthedocs.io/>`_ field definition. Here, ``ResourceIdField`` is a definition which de-serializes an ID (passed in as a request parameter) into a ``Resource`` instance. This instance can then be asked if the current user may read it. That last part is what ``@permission_required_for_context`` is doing. You can find these Marshmallow fields in ``flexmeasures.api.common.schemas``. 


Account roles
---------------

One means for this is to define custom account roles. E.g. if several services run on one FlexMeasures server, each service could define a "MyService-subscriber" account role. 

To make sure that only users of such accounts can use the endpoints:

.. code-block:: python

    @flexmeasures_ui.route("/bananas")
    @account_roles_required("MyService-subscriber")
    def bananas_view:
        pass

.. note:: This endpoint decorator lists required roles, so the authenticated user's account needs to have each role. You can also use the ``@account_roles_accepted`` decorator. Then the user's account only needs to have at least one of the roles.


User roles
---------------

There are also decorators to check user roles. Here is an example:

.. code-block:: python 

    @flexmeasures_ui.route("/bananas")
    @roles_required("account-admin")
    def bananas_view:
        pass

.. note:: You can also use the ``@roles_accepted`` decorator.
