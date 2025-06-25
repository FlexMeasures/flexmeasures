![FlexMeasures Logo Light](https://github.com/FlexMeasures/screenshots/blob/main/logo/flexmeasures-horizontal-color.svg#gh-light-mode-only)
![FlexMeasures Logo Dark](https://github.com/FlexMeasures/screenshots/blob/main/logo/flexmeasures-horizontal-dark.svg#gh-dark-mode-only)

[![License](https://img.shields.io/github/license/seitabv/flexmeasures?color=blue)](https://github.com/FlexMeasures/flexmeasures/blob/main/LICENSE)
![lint-and-test](https://github.com/FlexMeasures/flexmeasures/workflows/lint-and-test/badge.svg)
[![Pypi Version](https://img.shields.io/pypi/v/flexmeasures.svg)](https://pypi.python.org/pypi/flexmeasures)
[![](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Documentation Status](https://readthedocs.org/projects/flexmeasures/badge/?version=latest)](https://flexmeasures.readthedocs.io/en/latest/?badge=latest)
[![Coverage](https://coveralls.io/repos/github/FlexMeasures/flexmeasures/badge.svg)](https://coveralls.io/github/FlexMeasures/flexmeasures)
[![CII Best Practices](https://bestpractices.coreinfrastructure.org/projects/6095/badge)](https://bestpractices.coreinfrastructure.org/projects/6095)

*FlexMeasures* is an intelligent EMS (energy management system) to optimize behind-the-meter energy flexibility.
Build your smart energy apps & services with FlexMeasures as backend for real-time orchestration! 

In a nutshell, FlexMeasures turns data into optimized schedules for flexible assets like batteries and heat pumps, or for flexible industry processes:

![The most simple view of FlexMeasures, turning data into schedules](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/simple-flexEMS.png)


Here is why using FlexMeasures is a great idea:

- Developing energy flexibility apps & services (e.g. to enable demand response) is crucial, but expensive.
- FlexMeasures reduces development costs with real-time data intelligence & integrations, uncertainty models and developer support such as API/UI and plugins.

![High-level overview of FlexMeasures as an EMS for energy flexibility apps, using plugins to fit a given use case](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/overview-flexEMS.png)


So why optimise the schedules of flexible assets? Because planning ahead allows flexible assets to serve the whole system with their flexibility, e.g. by shifting energy consumption to other times.
For the asset owners, this creates CO₂ savings but also monetary value (e.g. through self-consumption, dynamic tariffs and grid incentives). FlexMeasures thrives to be applicable in cases with multiple sources of value ("value stacking") and multiple types of assets (e.g. home/office/factory).

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling. However, even small companies and hobby projects might find FlexMeasures useful!

## How does FlexMeasures enable rapid development of energy flexibility apps?

FlexMeasures is designed to help with three basic needs of developers in the energy flexibility domain:

### I need help with integrating real-time data and continuously computing new data

FlexMeasures is designed to make decisions based on data in an automated way. Data pipelining and dedicated machine learning tooling is crucial.

- API/CLI functionality to read in time series data
- Extensions for integrating 3rd party data, e.g. from [ENTSO-E](https://github.com/SeitaBV/flexmeasures-entsoe) or [OpenWeatherMap](https://github.com/SeitaBV/flexmeasures-openweathermap)
- Forecasting for the upcoming hours
- Schedule optimization for flexible assets


### It's hard to correctly model data with different sources, resolutions, horizons and even uncertainties

Much developer time is spent correcting data and treating it correctly, so that you know you are computing on the right knowledge.

FlexMeasures is built on the [timely-beliefs framework](https://github.com/SeitaBV/timely-beliefs), so we model this real-world aspect accurately:

- Expected data properties are explicit (e.g. unit, time resolution)
- Incoming data is converted to fitting unit and time resolution automatically
- FlexMeasures also stores who thought that something happened (or that it will happen), and when they thought so
- Uncertainty can be modelled (useful for forecasting)


### I want to build new features quickly, not spend days solving basic problems

Building customer-facing apps & services is where developers make impact. We make their work easy.

- FlexMeasures has well-documented API endpoints and CLI commands to interact with its model and data
- You can extend it easily with your own logic by writing plugins
- A backend UI shows you your assets in maps and your data in plots. There is also support for plots to be available per API, for integration in your own frontend
- Multi-tenancy ― model multiple accounts on one server. Data is only seen/editable by authorized users in the right account


## Getting started

Head over to our [documentation](https://flexmeasures.readthedocs.io), e.g. the [getting started guide](https://flexmeasures.readthedocs.io/en/latest/getting-started.html) or the [5-minute tutorial](https://flexmeasures.readthedocs.io/en/latest/tut/toy-example-from-scratch.html). Or find more information on [FlexMeasures.io](https://flexmeasures.io).

See also [Seita's Github profile](https://github.com/SeitaBV), e.g. for FlexMeasures plugin examples.


## Development & community

FlexMeasures was initiated by [Seita BV](https://www.seita.nl) in The Netherlands in order to make sure that smart backend software is available to all parties working with energy flexibility, no matter where they are working on their local energy transition.

We made FlexMeasures freely available under the Apache2.0 licence and it is now [an incubation project at the Linux Energy Foundation](https://www.lfenergy.org/projects/flexmeasures/).

Within the FlexMeasures project, [we welcome contributions](https://github.com/FlexMeasures/tsc/blob/main/CONTRIBUTING.md). You can also [learn more about our governance](https://github.com/Flexmeasures/tsc/blob/main/GOVERNANCE.md).

You can connect with the community here on GitHub (e.g. by creating an issue), on [the mailing list](https://lists.lfenergy.org/g/flexmeasures), on [the FlexMeasures channel within the LF Energy Slack](https://slack.lfenergy.org/) or [by contacting the current maintainers](https://seita.nl/who-we-are/#contact).
