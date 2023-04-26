.. _api-dev:

Developing on the API
============================================

The FlexMeasures API is the main way that third-parties can automate their interaction with FlexMeasures, so it's highly important.

This is a small guide for creating new versions of the API and its docs.

.. warning:: This guide was written for API versions below v3.0 and is currently out of date.

.. todo:: A guide for endpoint design, e.g. using Marshmallow schemas and common validators.

.. contents:: Table of contents
    :local:
    :depth: 2


Introducing a new API version
---------------------

Larger changes to the API, other than fixes and refactoring, should be done by creating a new API version.
In the guide we're assuming the new version is ``v1.1``.

Whether we need a new API version or not, doesn't have a clear set of rules yet.
Certainly backward-incompatible changes should require one, but as you'll see, there is also certain overhead in creating
a new version, so a careful trade-off is advised.

.. note:: For the rest of this guide we'll assume your new API version is ``v1_1``.


Set up new module with routes
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In ``flexmeasures/api`` create a new module (folder with ``__init__.py``\ ).
Copy over the ``routes.py`` from the previous API version.
By default we import all routes from the previous version:

.. code-block:: python

   from flexmeasures.api.v1 import routes as v1_routes, implementations as v1_implementations


Set the service listing for this version (or overwrite completely if needed):

.. code-block:: python

   v1_1_service_listing = copy.deepcopy(v1_routes.v1_service_listing)
   v1_1_service_listing["version"] = "1.1"


Then update and redecorate each API endpoint as follows:

.. code-block:: python

   @flexmeasures_api.route("/getService", methods=["GET"])
   @as_response_type("GetServiceResponse")
   @append_doc_of(v1_routes.get_service)
   def get_service():
       return v1_implementations.get_service_response(v1_1_service_listing)


Set up a new blueprint
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In the new module's ``flexmeasures/api/v1_1/__init.py__``\ , copy the contents of ``flexmeasures/api/v1/__init.py__`` (previous API version).
Change all references to the version name in the new file (for example: ``flexmeasures_api_v1`` should become ``flexmeasures_api_v1_1``\ ).

In ``flexmeasures/api/__init__.py`` update the version listing in ``get_versions()`` and register a blueprint for the new api version by adding:

.. code-block:: python

   from flexmeasures.api.v1_1 import register_at as v1_1_register_at
   v1_1_register_at(app) 


New or updated endpoint implementations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Write functionality of new or updated endpoints in:

.. code-block::

   flexmeasures/api/v1_1/implementations.py


Utility functions that are commonly shared between endpoint implementations of different versions should go in:

.. code-block::

   flexmeasures/api/common/utils


where we distinguish between response decorators, request validators and other utils.

Testing
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If you changed an endpoint in the new version, write a test for it.
Usually, there is no need to copy the tests for unchanged endpoints, if not a major API version is being released.

Test the entire api or just your new version:

.. code-block:: bash

   $ pytest -k api
   $ pytest -k v1_1

UI Crud
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In ``ui/crud``\ , we support FlexMeasures' in-built UI with Flask endpoints, which then talk to our internal API.
The routes used there point to an API version. You should consider updating them to point to your new version.


Documentation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In ``documentation/api`` start a new specification ``v1_1.rst`` with contents like this:

.. code-block:: RST

    .. _v1_1:

    Version 1.1
    ===========

    Summary
    -------

    .. qrefflask:: flexmeasures.app:create()
      :blueprints: flexmeasures_api, flexmeasures_api_v1_1
      :order: path
      :include-empty-docstring:

    API Details
    -----------

    .. autoflask:: flexmeasures.app:create()
      :blueprints: flexmeasures_api, flexmeasures_api_v1_1
      :order: path
      :include-empty-docstring:


If you are ready to publish the new specifications, enter your changes in ``documentation/api/change_log.rst`` and update the api toctree in ``documentation/index.rst``
to include the new version in the table of contents.

You're not done. Several sections in the API documentation list endpoints as examples. If you want other developers to use your new API version, make sure those examples reference the latest endpoints. Remember that `Sphinx autoflask <https://sphinxcontrib-httpdomain.readthedocs.io/en/stable/#module-sphinxcontrib.autohttp.flask>`_ likes to prefix the names of endpoints with the blueprint’s name, for example:

.. code-block:: RST

    .. autoflask:: flexmeasures.app:create()
       :endpoints: flexmeasures_api_v1_1.post_meter_data
