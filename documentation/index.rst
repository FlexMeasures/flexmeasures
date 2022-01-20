Welcome to the FlexMeasures documentation!
===================================================================

In a world with renewable energy, flexibility is crucial and valuable.
Planning ahead allows flexible assets to serve the whole system with their flexibility,
e.g. by shifting or curtailing energy use.
This can also be profitable for their owners.

The *FlexMeasures Platform* is the intelligent backend to support real-time energy flexibility apps, rapidly and scalable. 

- Developing energy flexibility services (e.g. to enable demand response) is crucial, but expensive.
- FlexMeasures reduces development costs with real-time data integrations, uncertainty models and API/UI support.

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling. However, even small companies and hobby projects might find FlexMeasures useful! 

Let's take a closer look at the three core values:


Real-time data intelligence & integration
-----------------------------------------

Energy flexibility services need to interact multiple times per day or hour. We equipped FlexMeasures with:

- Support for real-time updates
- Forecasting for the upcoming hours
- Schedule optimization


Uncertainty models
-----------------------

Dealing with uncertain forecasts and outcomes is crucial.

FlexMeasures is therefore built on the `timely-beliefs framework <https://github.com/SeitaBV/timely-beliefs>`_, so we model this real-world aspect accurately.


Service building
-----------------------
Building customer-facing services is where developers make impact. We make their work easy.

- Well-documented API
- Plugin support
- Plotting support
- Multi-tenancy


For more on FlexMeasures services, read :ref:`services`. Or head right over to :ref:`getting_started`.


Using FlexMeasures benefits operators as well as asset owners,
by allowing for automation, insight, autonomy and profit sharing.
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

    concepts/benefits
    concepts/benefits_of_flex
    concepts/inbuilt-smart-functionality
    concepts/algorithms
    concepts/security_auth


.. toctree::
    :caption: Tutorials
    :maxdepth: 1
    
    tut/posting_data
    tut/forecasting_scheduling
    tut/building_uis

.. toctree::
    :caption: The in-built UI
    :maxdepth: 1

    views/dashboard
    views/admin

.. toctree::
    :caption: The API 
    :maxdepth: 1

    api/introduction
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
    dev/auth
    dev/error-monitoring
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

