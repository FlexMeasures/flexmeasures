# Developing for FlexMeasures

Note: For developers, there is more detailed documentation available. Please consult the documentation next to the relevant code:

* [General coding tips and maintenance](flexmeasures/Readme.md)
* [Continuous Integration](ci/Readme.md)
* [Database management](flexmeasures/data/Readme.md)
* [API development](flexmeasures/api/Readme.md)


## Virtual environment

Using a virtual enviornment is best practice for Python developers. We also stringly recommend using a dedicated one for your work on FlexMeasures, as our make target (see below) will use `pip-sync` to install dependencies, which could interfere with some libraries you already have installed.

* Make a virtual environment: `python3.8 -m venv flexmeasures-venv` or use a different tool like `mkvirtualenv` or virtualenvwrapper. You can also use
  an [Anaconda distribution](https://conda.io/docs/user-guide/tasks/manage-environments.html) as base with `conda create -n flexmeasures-venv python=3.8`.
* Activate it, e.g.: `source flexmeasures-venv/bin/activate`


## Dependencies

Install all dependencies including the ones needed for development:

    make install-for-dev

## Configuration

Follow the confguration Quickstart advice in `Installation.md`.


## Loading data

If you have a SQL Dump file, you can load that:

    psql -U {user_name} -h {host_name} -d {database_name} -f {file_path}



## Run locally

Now, to start the web application, you can run:

    flexmeasures run

Or:

    python run-local.py

And access the server at http://localhost:5000


## Tests

You can run automated tests with:

    make test

which behind the curtains installs dependencies and calls pytest.

A coverage report can be created like this:

    pytest --cov=flexmeasures --cov-config .coveragerc

You can add --cov-report=html after which a htmlcov/index.html is generated.

It's also possible to use:

    python setup.py test


## Versioning

We use [setuptool_scm](https://github.com/pypa/setuptools_scm/) for versioning, which bases the FlexMeasures version on the latest git tag and the commits since then.

So as a developer, it's crucial to use git tags for versions only.

We use semantic versioning, and we always include the patch version, not only max and min, so that setuptools_scm makes the correct guess about the next minor version. Thus, we should use `2.0.0` instead of `2.0`.

See `to_pypi.sh` for more commentary on the development versions.

Our API has its own version, which moves much slower. This is important to explicitly support outside apps who were coded against older versions. 