# The FlexMeasures Platform

[![License](https://img.shields.io/github/license/seitabv/flexmeasures?color=blue)](https://github.com/FlexMeasures/flexmeasures/blob/main/LICENSE)
![lint-and-test](https://github.com/FlexMeasures/flexmeasures/workflows/lint-and-test/badge.svg)
[![Pypi Version](https://img.shields.io/pypi/v/flexmeasures.svg)](https://pypi.python.org/pypi/flexmeasures)
[![](https://img.shields.io/badge/python-3.6+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Documentation Status](https://readthedocs.org/projects/flexmeasures/badge/?version=latest)](https://flexmeasures.readthedocs.io/en/latest/?badge=latest)
[![Coverage](https://coveralls.io/repos/github/FlexMeasures/flexmeasures/badge.svg?branch=coverage-in-ci)](https://coveralls.io/github/FlexMeasures/flexmeasures?branch=coverage-in-ci)

The *FlexMeasures Platform* is the intelligent backend to support real-time energy flexibility apps, rapidly and scalable. 

- Developing energy flexibility apps & services (e.g. to enable demand response) is crucial, but expensive.
- FlexMeasures reduces development costs with real-time data intelligence & integrations, uncertainty models and API/UI support.

![Separation of concerns ― FlexMeasures enhancing Energy Service Company services](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/SeparationOfConcerns.png)

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling. However, even small companies and hobby projects might find FlexMeasures useful! 

## What does FlexMeasures provide?

A closer look at FlexMeasures' three core value drivers:

1. Real-time data intelligence and integration, with advice for the rest of the day. For example, forecasts and schedules are made available via API (designed with [the USEF framework](https://usef.energy) in mind).
2. Energy sensor and environment data have multiple sources and their forecasts are uncertain. FlexMeasures uses the [timely-beliefs library](https://github.com/SeitaBV/timely-beliefs) to model this well.
3. Developer support ― building customer-facing apps & services is where energy flexibility hits the road. FlexMeasures reduces developer workload with a well-documented API, data visualisation and multi-tenancy, and it supports plugins to customise and extend the platform to your needs.


![Integration view of the FlexMeasures platform architecture](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/FlexMeasures-HighLevel.png)


## Getting started

Head over to our [documentation](https://flexmeasures.readthedocs.io), e.g. the [getting started guide](https://flexmeasures.readthedocs.io/en/latest/getting-started.html). Or find more information on [FlexMeasures.io](https://flexmeasures.io).

See also [Seita's Github profile](https://github.com/SeitaBV), e.g. for FlexMeasures plugin examples.


## Development & community

FlexMeasures was initiated by [Seita BV](https://www.seita.nl) in The Netherlands in order to make sure that smart backend software is available to all parties working with energy flexibility, no matter where they are working on their local energy transition.

We made FlexMeasures freely available under the Apache2.0 licence.

Within the FlexMeasures project, [we welcome contributions](https://github.com/FlexMeasures/tsc/blob/main/CONTRIBUTING.md). You can also [learn more about our governance](https://github.com/Flexmeasures/tsc/blob/main/GOVERNANCE.md).

You can connect with the community here on Github (e.g. by creating an issue), on [the mailing list](https://lists.lfenergy.org/g/flexmeasures), on [the FlexMeasures channel within the LF Energy Slack](https://slack.lfenergy.org/) or [by contacting the current maintainers](https://www.seita.nl/contact).