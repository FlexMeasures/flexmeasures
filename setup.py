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
        ]
    return reqs


setup(
    name="flexmeasures",
    description="FlexMeasures - A free platform for real-time optimization of flexible energy.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    url="https://github.com/seitabv/flexmeasures",
    keywords=["smart grid", "renewables", "balancing", "forecasting", "scheduling"],
    python_requires=">=3.7.1",  # not enforced, just info
    install_requires=load_requirements("app"),
    tests_require=load_requirements("test"),
    setup_requires=["pytest-runner", "setuptools_scm"],
    use_scm_version={"local_scheme": "no-local-version"},  # handled by setuptools_scm
    packages=find_packages(),
    include_package_data=True,  # setuptools_scm takes care of adding the files in SCM
    entry_points={
        "console_scripts": [
            "flexmeasures=flexmeasures.utils.app_utils:flexmeasures_cli"
        ],
    },
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.7",
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
