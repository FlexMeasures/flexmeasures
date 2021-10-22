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
    description="The *FlexMeasures Platform* - a tool for building real-time energy flexibility services, rapidly and scalable.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    url="https://github.com/seitabv/flexmeasures",
    keywords=["smart grid", "renewables", "balancing", "forecasting", "scheduling"],
    python_requires=">=3.7.1",  # not enforced, just info
    install_requires=load_requirements("app"),
    tests_require=load_requirements("test"),
    setup_requires=["pytest-runner", "setuptools_scm"],
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
        "Programming Language :: Python :: 3.7",
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    long_description="""\
The *FlexMeasures Platform* is a tool for building real-time energy flexibility services, rapidly and scalable.

In a world with renewable energy, flexibility is crucial and valuable.
Planning ahead allows flexible assets to serve the whole system with their flexibility,
e.g. by shifting or curtailing energy use. This can also be profitable for their owners.

- Developing energy flexibility services (e.g. to enable demand response) is crucial, but expensive.
- To enable rapid creation of scalable services, we offer the FlexMeasures platform. For free.
- FlexMeasures reduces development costs with real-time data integrations, uncertainty models and API/UI support.

For this purpose, it delivers three core values:


 * Real-time updates & advice ― Support for real-time updates, forecasting for the upcoming hours & schedule optimization.
 * Uncertainty models ― Dealing with uncertain forecasts and outcomes is crucial. FlexMeasures is built on [timely-beliefs](https://github.com/SeitaBV/timely-beliefs), so we model this real-world aspect accurately.
 * Service building ― Building customer-facing services is where developers make impact. We make their work easy with a well-documented API (inspired by the Universal Smart Energy Framework - USEF), plugin support & plotting support.

Energy Flexibility is one of the key ingredients to reducing CO2. FlexMeasures is meant
to facilitate the transition to a carbon-free energy system. By open-sourcing FlexMeasures,
we hope to speed up this transition world-wide.

Please visit https://flexmeasures.io to learn more.
""",
)
