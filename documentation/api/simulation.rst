.. _simulation:

Simulation
==========

This document details examples for using the BVP **play** server for simulation.
The API on this server is extended with several features that make it possible to run simulations of energy flows and balancing valorisation.
Please read the :ref:`introduction` for explanations of the message fields, specifically regarding:

- The sign of values (:ref:`signs`)
- Valid durations (:ref:`resolutions`)
- Valid horizons (:ref:`prognoses`)
- Valid units (:ref:`units`)

Setting up
----------

The researcher requires an admin account to set up a new simulation with a number of assets.

Creating assets and owners
^^^^^^^^^^^^^^^^^^^^^^^^^^

New assets can be created through the UI on:

.. code-block:: html

    https://play.a1-bvp.com/assets/new


We recommend that the researcher chooses its own admin account as the asset's owner.
This way, the simulation will require only a single access token.
Alternatively, the researcher can set up unique accounts for each agent in a multi-agent simulation by creating new owners.

Authentication
^^^^^^^^^^^^^^

Service usage is only possible with a user authentication token specified in the request header, for example:

.. code-block:: json

    {
        "Authorization": "<token>"
    }

The "<token>" can be obtained on your profile after logging in:

.. code-block:: html

    https://play.a1-bvp.com/account


Posting meter data
------------------

Meter data can be posted in various ways.

Single value, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A single average power value for a 15-minute time interval for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "value": "220",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Multiple values, single connection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for a single connection, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "values": [
            "220",
            "210",
            "200"
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H45M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Single identical value, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Single identical value for a 15-minute time interval for two connections, posted 5 minutes after realisation.
Please note that both connections consumed at 10 MW, i.e. the value does not represent the total of the two connections.
We recommend to use this notation for zero values only.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "connections": [
            "ea1.2018-06.com.a1-bvp.play:1:1",
            "ea1.2018-06.com.a1-bvp.play:1:2"
        ],
        "value": 10,
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Single different values, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Single different values for a 15-minute time interval for two connections, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
                "value": 220
            },
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:2",
                "value": 300
            }
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H15M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Multiple values, multiple connections
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Multiple values (indicating a univariate timeseries) for 15-minute time intervals for two connections, posted 5 minutes after realisation.

.. code-block:: json

    {
        "type": "PostMeterDataRequest",
        "groups": [
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
                "values": [
                    220,
                    210,
                    200
                ]
            },
            {
                "connection": "ea1.2018-06.com.a1-bvp.play:1:2",
                "values": [
                    300,
                    303,
                    306
                ]
            }
        ],
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT0H45M",
        "horizon": "-PT5M",
        "unit": "MW"
    }

Getting prognoses
-----------------

A prognosis can be requested for a single asset. This example requests a prognosis with a rolling horizon of 6 hours before realisation.

.. code-block:: json

    {
        "type": "GetPrognosisRequest",
        "connection": "ea1.2018-06.com.a1-bvp.play:1:1",
        "start": "2015-01-01T00:00:00+00:00",
        "duration": "PT24H",
        "horizon": "R/PT6H",
        "resolution": "PT15M",
        "unit": "MW"
    }
