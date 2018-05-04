from setuptools import setup

setup(
    name="bvp",
    description="Balancing Valorisation Platform.",
    author="Seita BV",
    author_email="nicolas@seita.nl",
    keywords=["smart grid", "renewables", "balancing", "forecasting"],
    version="0.1",
    install_requires=["flask", "bokeh", "pandas>=0.22.0", "iso8601", "xlrd", "inflection", "humanize", "Flask-SSLify",
                      "psycopg2-binary", "Flask-SQLALchemy", "Flask-Migrate", "Flask-Classful", "Flask-WTF", "Flask-Mail",
                      "Flask-Security", "bcrypt", "pytz", "numpy", "click", "forecastiopy", "python-dotenv"],
    tests_require = ["pytest", "pytest-flask"],
    packages=["bvp"],
    include_package_data=True,
    #license="Apache",
    classifiers = [
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Operating System :: OS Independent",
        ],
    long_description="""\
The *Balancing Valorisation Platform (BVP)* is a tool for scheduling balancing actions on behalf of the connected asset owners.
Its purpose is to offer these balancing actions as one aggregated service to energy markets, realising the highest possible value for its users.
"""
)
