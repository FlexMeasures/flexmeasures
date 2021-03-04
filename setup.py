from setuptools import setup, find_packages

from flexmeasures import __version__


def load_requirements(use_case):
    reqs = []
    with open("requirements/%s.in" % use_case, "r") as f:
        reqs = [
            req
            for req in f.read().splitlines()
            if not req.strip() == ""
            and not req.strip().startswith("#")
            and not req.strip().startswith("-c")
        ]
    return reqs


setup(
    name="flexmeasures",
    description="FlexMeasures - A free platform for real-time optimization of flexible energy.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    url="https://github.com/seitabv/flexmeasures",
    keywords=["smart grid", "renewables", "balancing", "forecasting", "scheduling"],
    version=__version__,
    install_requires=load_requirements("app"),
    setup_requires=["pytest-runner"],
    tests_require=load_requirements("test"),
    packages=find_packages(),
    include_package_data=True,  # see MANIFEST.in
    entry_points={
        "console_scripts": [
            "flexmeasures=flexmeasures.utils.app_utils:flexmeasures_cli"
        ],
    },
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    long_description="""\
The *FlexMeasures Platform* is a tool for scheduling flexible actions for energy assets.
For this purpose, it performs monitoring, forecasting and scheduling services.

FlexMeasures is fully usable via APIs, which are inspired by the Universal Smart Energy Framework (USEF).
Some algorithms are included, but projects will usually write their own (WIP).

Energy Flexibility is one of the key ingredients to reducing CO2. FlexMeasures is meant
to facilitate the transition to a carbon-free energy system. By open-sourcing FlexMeasures,
we hope to speed up this transition world-wide.

Please visit https://flexmeasures.io to learn more.
""",
)
