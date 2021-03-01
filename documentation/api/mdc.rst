.. _mdc:

Meter Data Company
==================

The meter data company (MDC) represents a trusted party that shares the meter data of connections that are
registered within FlexMeasures. In case the MDC cannot be queried to provide relevant meter data (e.g. because the role
has not taken up by a market party), the party taking up the Prosumer role will also take up the MDC role, and will
bear the responsibility to post their own meter data with the *postMeterData* service.

The granularity of the meter data and the time delay between the actual measurement and its posting should be
specified in the service contract between Prosumer and Aggregator. In this example, the Prosumer decided to share
the meter data in 15-minute intervals and only after 1.30am. It is desirable to send meter readings in 5-minute
intervals (or with an even finer granularity), and as soon as possible after measurement.

.. autoflask:: flexmeasures.app:create(env="documentation")
    :endpoints: flexmeasures_api_v1_1.post_meter_data
