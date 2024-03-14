.. _getting_started:

Getting started
=================================

For a direct intro on running FlexMeasures, go to :ref:`installation`. However, FlexMeasures is useful from different perspectives.
Below, we added helpful pointers to start reading.

.. contents::
    :local:
    :depth: 2


.. _start_using_flexmeasures_in_your_organization:

For organizations
------------------

We make FlexMeasures, so that your software developers are as productive with energy optimization as possible. Because we are developers ourselves, we know that it takes a couple smaller steps to engage with new technology. 

Your journey, from dipping your toes in the water towards being a productive energy optimization company, could look like this:

1. Quickstart ― Find an optimized schedule for your flexible asset, like a battery, with standard FlexMeasures tooling. This is basically what we show in :ref:`tut_toy_schedule`. All you need are 10 minutes and a CSV file with prices to optimize against.
2. Automate ― get the prices from an open API, for instance `ENTSO-E <https://transparency.entsoe.eu/>`_ (using a plugin like `flexmeasures-entsoe <https://github.com/SeitaBV/flexmeasures-entsoe>`_), and run the scheduler regularly in a cron job.
3. Integrate ― Load the schedules via FlexMeasures' API, so you can directly control your assets and/or show them within your own frontend.
4. Customize ― Load other data (e.g. your solar production or weather forecasts via `flexmeasures-openweathermap <https://github.com/SeitaBV/flexmeasures-openweathermap/>`_). Adapt the algorithms, e.g. do your own forecasting or tweak the standard scheduling algorithm so it optimizes what you care about. Or write a plugin for accessing a new kind of market. The opportunities are endless!




For Individuals
----------------

Using FlexMeasures
^^^^^^^^^^^^^^^^^^^

You are connecting to a running FlexMeasures server, e.g. for sending data, getting schedules or administrate users and assets. 

First, you'll need an account from the party running the server. Also, you probably want to:

- Look at the UI, e.g. pages for :ref:`dashboard` and :ref:`admin`.
- Read the :ref:`api_introduction`.
- Learn how to interact with the API in :ref:`tut_posting_data`.


Hosting FlexMeasures
^^^^^^^^^^^^^^^^^^^^^^

You want to run your own FlexMeasures instance, to offer services or for trying it out. You'll want to:

- Have a first playful scheduling session, following :ref:`tut_toy_schedule`.
- Get real with the tutorial on :ref:`installation`.
- Discover the power of :ref:`cli`.
- Understand how to :ref:`deployment`.


Plugin developers
^^^^^^^^^^^^^^^^^^

You want to extend the functionality of FlexMeasures, e.g. a custom integration or a custom algorithm:

- Read the docs on :ref:`plugins`.
- See how some existing plugins are made `flexmeasures-entsoe <https://github.com/SeitaBV/flexmeasures-entsoe>`_ or `flexmeasures-openweathermap <https://github.com/SeitaBV/flexmeasures-openweathermap>`_
- Of course, some of the developers resources (see below) might be helpful to you, as well.


Core developers
^^^^^^^^^^^^^^^^

You want to help develop FlexMeasures, e.g. to fix a bug. We provide a getting-started guide to becoming a developer at :ref:`developing`.

