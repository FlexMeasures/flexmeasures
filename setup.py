from setuptools import setup, find_packages


def load_requirements(use_case):
    reqs = []
    with open("requirements/%s.txt" % use_case, "r") as f:
        reqs = [
            req
            for req in f.read().splitlines()
            if not req.strip() == ""
            and not req.strip().startswith("#")
            and not req.strip().startswith("-c")
            and not req.strip().startswith("--find-links")
        ]
    return reqs


setup(
    name="flexmeasures",
    description="The *FlexMeasures Platform* is the intelligent backend to support real-time energy flexibility apps, rapidly and scalable.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    url="https://github.com/seitabv/flexmeasures",
    keywords=["smart grid", "renewables", "balancing", "forecasting", "scheduling"],
    python_requires=">=3.8",  # not enforced, just info
    install_requires=load_requirements("app"),
    setup_requires=["setuptools_scm"],
    use_scm_version={"local_scheme": "no-local-version"},  # handled by setuptools_scm
    packages=find_packages(),  # will include *.py files and some other types
    include_package_data=True,  # now setuptools_scm adds all files under source control
    entry_points={
        "console_scripts": [
            "flexmeasures=flexmeasures.utils.app_utils:flexmeasures_cli"
        ],
    },
    license="Apache2.0",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    long_description="""\
The *FlexMeasures Platform* is the intelligent backend to support real-time energy flexibility apps, rapidly and scalable.

In a world with renewable energy, flexibility is crucial and valuable.
Planning ahead allows flexible assets to serve the whole system with their flexibility,
e.g. by shifting or curtailing energy use. This can also be profitable for their owners.

- Developing energy flexibility apps & services (e.g. to enable demand response) is crucial, but expensive.
- FlexMeasures reduces development costs with real-time data intelligence & integrations, uncertainty models and API/UI support.

As possible users, we see energy service companies (ESCOs) who want to build real-time apps & services around energy flexibility for their customers, or medium/large industrials who are looking for support in their internal digital tooling. However, even small companies and hobby projects might find FlexMeasures useful!

A closer look at FlexMeasures' three core value drivers:

 * Real-time data intelligence & integration ― Support for real-time updates, forecasting for the upcoming hours & schedule optimization.
 * Uncertainty models ― Dealing with uncertain forecasts and outcomes is crucial. FlexMeasures is built on [timely-beliefs](https://github.com/SeitaBV/timely-beliefs), so we model this real-world aspect accurately.
 * Developer support ― Building customer-facing apps & services is where developers make impact. FlexMeasures make their work easy with a well-documented API, data visualisation and multi-tenancy, and it supports plugins to customise and extend the platform to your needs.

Energy Flexibility is one of the key ingredients to reducing CO2. FlexMeasures is meant
to facilitate the transition to a carbon-free energy system. By open-sourcing FlexMeasures,
we hope to speed up this transition world-wide.

Please visit https://flexmeasures.io to learn more.
""",
)
