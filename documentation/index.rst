Welcome to the FlexMeasures documentation!
===================================================================

In a world with renewable energy, flexibility is crucial and valuable.
Planning ahead allows flexible assets to serve the whole system with their flexibility,
e.g. by shifting or curtailing energy use.
This can also be profitable for their owners.

The FlexMeasures Platform is a tool for scheduling flexibility activations for energy assets.
For this purpose, it performs three services:

* Monitoring of incoming measurements
* Forecasting of expected measurements
* Scheduling flexibility activations with custom optimisation

For more on FlexMeasures services, read :ref:`services`. Or head right over to :ref:`getting_started`.


Using FlexMeasures benefits operators as well as asset owners,
by allowing or automation, insight, autonomy and profit sharing.
For more on benefits, consult :ref:`benefits`.

FlexMeasures is compliant with the `Universal Smart Energy Framework (USEF) <https://www.usef.energy/>`_.
Therefore, this documentation uses USEF terminology, e.g. for role definitions.
The intended users of FlexMeasures are a Supplier (energy company) and its Prosumers (asset owners who have energy contracts with that Supplier).
The platform operator of FlexMeasures can be an Aggregator.


.. toctree::
   :maxdepth: 1
   :hidden:

   getting-started
   configuration
   changelog

.. toctree::
    :caption: Concepts
    :maxdepth: 1

    concepts/services
    concepts/benefits
    concepts/benefits_of_flex
    concepts/algorithms
    concepts/security_auth


.. toctree::
    :caption: The in-built UI
    :maxdepth: 1

    views/dashboard
    views/portfolio
    views/control
    views/analytics
    views/admin

.. toctree::
    :caption: The API 
    :maxdepth: 1

    api/introduction
    api/simulation
    api/v2_0
    api/v1_3
    api/v1_2
    api/v1_1
    api/v1
    api/change_log

.. toctree::
    :caption: The CLI 
    :maxdepth: 1

    cli/commands
    cli/change_log


.. toctree::
    :caption: Developers
    :maxdepth: 1

    dev/introduction
    dev/data
    dev/api
    dev/ci
    dev/plugins
    dev/modes

.. toctree::
    :caption: Integrations
    :maxdepth: 2

    int/introduction


Code documentation
------------------

Go To :ref:`source`.



.. Indices and tables
.. ==================

.. * :ref:`genindex`
.. * :ref:`modindex`
.. * :ref:`search`

