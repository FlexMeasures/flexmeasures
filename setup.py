from setuptools import setup


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
    name="bvp",
    description="Balancing Valorisation Platform.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    keywords=["smart grid", "renewables", "balancing", "forecasting", "scheduling"],
    version="0.2",
    install_requires=load_requirements("app"),
    setup_requires=["pytest-runner"],
    tests_require=load_requirements("test"),
    packages=["bvp"],
    include_package_data=True,
    # license="Apache",
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Operating System :: OS Independent",
    ],
    long_description="""\
The *Balancing Valorisation Platform (BVP)* is a tool for scheduling balancing actions on behalf of the connected
asset owners. Its purpose is to offer these balancing actions as one aggregated service to energy markets,
realising the highest possible value for its users.
""",
)
