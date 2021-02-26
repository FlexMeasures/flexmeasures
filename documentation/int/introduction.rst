.. _integrations_introduction:

Introduction
============

The platform's functionality can be integrated into any third-party workflow by using the :ref:`API <api_introduction>`.
In this section we discuss several examples of third-party IoT software for integrating with hardware devices.
These systems may be considered especially useful for Aggregators, Energy Service Companies and Prosumers.
Third-party software for other stakeholders (such as Suppliers, DSOs and TSOs) are proprietary systems for which open documentation is not adequately available.

.. _home_assistant:

Home Assistant
==============

Home Assistant is an open-source system for hardware-software integration, supporting >1200 hardware components and software services.
The system is written in Python, designed to run on a lightweight local server (such as a Raspberry Pi) and geared towards the residential sector.

.. code-block:: html

    https://home-assistant.io

One of the supported integrations is with Z-Wave components such as the Z-Wave Aeotec clamp power meter.

.. code-block:: html

    https://aeotec.com/z-wave-home-energy-measure

To collect meter data from individual devices, the local server should be fitted with a Z-stick.
An advantage of Z-Wave wireless communication technology is that it operates as a mesh network.
This means that adding a Z-Wave component to the local system extends the system's communication range.
The maximum range of individual Z-Wave components is approximately 30 meters.

.. _smappee:

Smappee
=======

Smappee is a proprietary system providing a suite of services supporting full hardware-software integration.
The system is geared towards the residential sector.

.. code-block:: html

    https://smappee.com

Products include sub-metering using power clamps, plug-and-play power socket actuators and analysis dashboards.
In addition, it offers software integrations with several other smart home products and services,
such as a number of brands of thermostats and air conditioning.

Smappee may be integrated with the BPV platform using Smappy,
a Python wrapper for the Smappee API, which can retrieve sensor data and control actuators.

.. code-block:: html

    https://github.com/EnergieID/smappy/wiki

The API can be used to retrieve meter data (with a specific resolution) of individual devices using the `get_sensor_consumption` function.
This data can then be sent to FlexMeasures using the `post_meter_data` endpoint.
In addition, device messages from FlexMeasures intended to curtail consumption (for a specific duration) can be sent to individual devices using the `actuator_off` function.
