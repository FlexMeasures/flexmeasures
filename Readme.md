# The FlexMeasures Platform

[![License](https://img.shields.io/github/license/seitabv/flexmeasures?color=blue)](https://github.com/FlexMeasures/flexmeasures/blob/main/LICENSE)
![lint-and-test](https://github.com/FlexMeasures/flexmeasures/workflows/lint-and-test/badge.svg)
[![Pypi Version](https://img.shields.io/pypi/v/flexmeasures.svg)](https://pypi.python.org/pypi/flexmeasures)
[![](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Documentation Status](https://readthedocs.org/projects/flexmeasures/badge/?version=latest)](https://flexmeasures.readthedocs.io/en/latest/?badge=latest)

The *FlexMeasures Platform* is a tool for building real-time energy flexibility services, rapidly and scalable. 

- Developing energy flexibility services (e.g. to enable demand response) is crucial, but expensive.
- FlexMeasures reduces development costs with real-time data integrations, uncertainty models and API/UI support.

![Separation of concerns ― FlexMeasures enhancing Energy Service Company services](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/SeparationOfConcerns.png)


With services and data integrations built on top of FlexMeasures, energy service companies (ESCOs) can offer real-time services around energy flexibility.

FlexMeasures provides three core values:

1. Real-time data integration support, with advice for the rest of the day. For example, forecasts and schedules are made available via API (designed with [the USEF framework](https://usef.energy) in mind).
2. Energy sensor and environment data have multiple sources and their forecasts are uncertain. FlexMeasures uses the [timely-beliefs library](https://github.com/SeitaBV/timely-beliefs) to model this well.
3. Developer support ― building customer-facing services is where energy flexibility hits the road. FlexMeasures reduces developer workload with a well-documented API, data visualisation and multi-tenancy, and supports plugins to customise and extend the platform to your needs.


![Integration view of the FlexMeasures platform architecture](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-HighLevel.png)

FlexMeasures is developed by [Seita BV](https://www.seita.nl) in The Netherlands.

We made FlexMeasures freely available under the Apache2.0 licence. Please get in contact if you use FlexMeasures or are considering it.

Head over to our [documentation](https://flexmeasures.readthedocs.io), e.g. the [getting started guide](https://flexmeasures.readthedocs.io/en/latest/getting-started.html). Or find more information on [FlexMeasures.io](https://flexmeasures.io).

