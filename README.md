![FlexMeasures Logo Light](https://github.com/FlexMeasures/screenshots/blob/main/logo/flexmeasures-horizontal-color.svg#gh-light-mode-only)
![FlexMeasures Logo Dark](https://github.com/FlexMeasures/screenshots/blob/main/logo/flexmeasures-horizontal-dark.svg#gh-dark-mode-only)

[![License](https://img.shields.io/github/license/seitabv/flexmeasures?color=blue)](https://github.com/FlexMeasures/flexmeasures/blob/main/LICENSE)
![lint-and-test](https://github.com/FlexMeasures/flexmeasures/actions/workflows/lint-and-test.yml/badge.svg)
[![Pypi Version](https://img.shields.io/pypi/v/flexmeasures.svg)](https://pypi.python.org/pypi/flexmeasures)
[![](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Documentation Status](https://readthedocs.org/projects/flexmeasures/badge/?version=latest)](https://flexmeasures.readthedocs.io/latest/?badge=latest)
[![Coverage](https://coveralls.io/repos/github/FlexMeasures/flexmeasures/badge.svg?kill_cache=1)](https://coveralls.io/github/FlexMeasures/flexmeasures)
[![CII Best Practices](https://bestpractices.coreinfrastructure.org/projects/6095/badge)](https://bestpractices.coreinfrastructure.org/projects/6095)

*FlexMeasures* is an energy scheduling and optimization engine for powerful energy management systems. With FlexMeasures, you can integrate complex, multi-asset, multi-commodity optimization capabilities into your EMS. 


![The most simple view of FlexMeasures, turning data into schedules](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/simple-flexEMS.png)

FlexMeasures was created by and continues to be maintained by [Seita Energy Flexibility BV](https://www.seita.nl) in The Netherlands.

We fundamentally believe that the ability to schedule and optimize energy consumption across multiple assets and multiple energy sources is critical to the adoption of renewable energy and for energy diversification in general. At the same time, the models that power energy optimization need to be auditable and transparent, which is why we've created FlexMeasures as an open source project. 

Here's why you should integrate FlexMeasures into your Energy Management System: 

- End users expect energy management systems to include scheduling and optimization capabilities, but doing so is complicated and most energy management system creators aren't experts in scheduling and optimization. 
- FlexMeasures makes it easier for EMS creators to provide optimization and scheduling functionality with real-time data intelligence & integrations, uncertainty models and developer support such as API/UI and plugins.

![High-level overview of FlexMeasures as an EMS for energy flexibility apps, using plugins to fit a given use case](https://raw.githubusercontent.com/FlexMeasures/screenshots/main/architecture/overview-flexEMS.svg)


What's unique about FlexMeasures: 

- Flexibility. With FlexMeasures, you can manage complex optimizations that include multiple asset types, multiple commodities and value-stacking. It's also easy to customize, so you can also integrate your specific business logic into the optimizations.
- Transparency. FlexMeasures is built using mathematical formulas and is open source and inspectable. You can see how the optimization decisions are made and audit the process.
- Cost savings. Your customers will save money and reduce their carbon footprint. 

FlexMeasures is ideally suited for:

- Situations where you need to optimize for many different energy use cases, such as batteries, electric vehicles, heating/cooling and more, often simultaneously.
- Organizations that don't have in-house energy optimization and scheduling expertise
- Large organizations with enterprise-level requirements around security and auditing
- End users with complex scheduling and optimization needs. 

## For developers: Frequently asked questions about integrating energy scheduling and optimization into an EMS: 


### I need help with integrating real-time data and continuously computing new data

FlexMeasures is designed to make decisions based on data in an automated way. Data pipelining and dedicated machine learning tooling is crucial.

- API/CLI functionality to read in time series data
- Extensions/Plugins for integrating 3rd party data (e.g. from [ENTSO-E](https://github.com/SeitaBV/flexmeasures-entsoe), [OpenWeatherMap/WeatherAPI](https://github.com/flexmeasures/flexmeasures-weather)) or protocols (e.g. [OpenADR](https://github.com/FlexMeasures/flexmeasures-openadr3))
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
- A backend UI shows you your assets in maps and your data in plots (try the Replay button!). There is also support for plots to be available per API, for integration in your own frontend
- Multi-tenancy ― model multiple accounts on one server. Data is only seen/editable by authorized users in the right account


## Getting started

Head over to our [documentation](https://flexmeasures.readthedocs.io), e.g. the [getting-started guide](https://flexmeasures.readthedocs.io/latest/getting-started.html#getting-started) or the [5-minute tutorial](https://flexmeasures.readthedocs.io/latest/tut/toy-example-setup.html). Or find more information on [FlexMeasures.io](https://flexmeasures.io).

See also [Seita's Github profile](https://github.com/SeitaBV), e.g. for FlexMeasures plugin examples.


## Development & community

FlexMeasures is available under the permissive Apache2.0 licence and it is [an incubation project at the Linux Energy Foundation](https://www.lfenergy.org/projects/flexmeasures/).

Within the FlexMeasures project, [we welcome contributions](https://github.com/FlexMeasures/tsc/blob/main/CONTRIBUTING.md). A list of contributing organizations:

- Seita Energy Flexibility (NL, maintainer)
- Thiink (US)
- ELaad (NL)
- LUO (BE)

You can also [learn more about our governance](https://github.com/Flexmeasures/tsc/blob/main/GOVERNANCE.md).

You can connect with the community here on GitHub (e.g. by creating an issue), on [the FlexMeasures channel within the LF Energy Slack](https://slack.lfenergy.org/), on [the mailing list](https://lists.lfenergy.org/g/flexmeasures) or [by contacting the current maintainers](https://seita.nl/who-we-are/#contact).
