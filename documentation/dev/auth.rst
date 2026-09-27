.. _auth-dev:

Custom authorization
======================

Our :ref:`authorization` section describes general authorization handling in FlexMeasures.

If you are creating your own API endpoints for a custom energy flexibility service (on top of FlexMeasures), you should also get your authorization right. 
It's recommended to get familiar with the decorators we provide. Here are some pointers, but feel free to read more in the ``flexmeasures.auth`` package. 

In short, we recommend to use the ``@permission_required_for_context`` decorator (more explanation below).

FlexMeasures also supports role-based decorators, e.g. ``@account_roles_required``. These decorators do not check whether the user may perform a named action on a particular resource. [#f1]_

Finally, all decorators available through `Flask-Security-Too <https://flask-security-too.readthedocs.io/en/stable/patterns.html#authentication-and-authorization>`_ can be used, e.g. ``@auth_required`` (that's technically only checking authentication) or ``@permissions_required``.


Permission-based authorization
--------------------------------

Named permissions describe actions such as ``read``, ``post-data`` and ``trigger-schedules``. The names are declared in ``flexmeasures.auth.policy``. The ``Role.permissions`` property maps built-in user roles to those names in code; there is no permissions column on ``Role`` to populate. A model's ``__acl__`` maps the same names to principals allowed to perform them on that resource.

An endpoint must check both requirements with ``@permission_required_for_context`` or ``check_access``: the user needs an eligible role grant and must match an ACL principal for the resource. For example, ``trigger-schedules`` in an asset's ACL and in an endpoint check refers to the same permission as ``trigger-schedules`` in a role's grants. There is no separate capability identifier or ``cap:`` principal. Here is an example (taken from the decorator docstring):

.. code-block:: python

    @app.route("/resource/<resource_id>", methods=["GET"])
    @use_kwargs(
        {"the_resource": ResourceIdField(data_key="resource_id")},
        location="path",
    )
    @permission_required_for_context("read", ctx_arg_name="the_resource")
    @as_json
    def view(resource_id: int, resource: Resource):
        return dict(name=resource.name)

``@use_kwargs`` uses a `Marshmallow <https://marshmallow.readthedocs.io/>`_ field to deserialize the ID into a ``Resource`` instance. ``@permission_required_for_context`` then checks whether the current user may read that instance. You can find these fields in ``flexmeasures.api.common.schemas``.

Home roles (``member``, ``account-admin``, ``read-only`` and ``integration``) provide grants only when the matching ACL principal refers to the user's own account. The ``consultant`` role provides grants only through a matching consultancy principal on a client resource. The site-wide ``admin`` and ``admin-reader`` roles are exceptions. Grant and ACL scope must match in the same ACL alternative; having ``member`` in a home account does not supply permissions while acting as a consultant for a client account. Unknown user roles grant no built-in named permissions. Custom services can still define their own authorization behavior for their endpoints.

Existing users receive the ``member`` role in a data migration so their previous implicit home-account access persists; a following migration creates the ``read-only`` and ``integration`` role rows. Newly created users receive it by default unless explicit roles are supplied. Roles only add grants, so remove ``member`` when converting a user to ``read-only`` or ``integration``.


Account roles
---------------

Another way to implement custom authorization is to define custom account roles. E.g. if several services run on one FlexMeasures server, each service could define a "MyService-subscriber" account role. 

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


.. rubric:: Footnotes

.. [#f1] Some authorization features are not possible for endpoints decorated in this way. For instance, we have an ``admin-reader`` role who should be able to read but not write everything ― with only role-based decorators we can not allow this user to read (as we don't know what permission the endpoint requires).
