# Developing for FlexMeasures

Note: For developers, there is more detailed documentation available. Please consult the documentation next to the relevant code:

* [General coding tips and maintenance](flexmeasures/Readme.md)
* [Continuous Integration](ci/Readme.md)
* [Database management](flexmeasures/data/Readme.md)
* [API development](flexmeasures/api/Readme.md)


## Virtual environment

* Make a virtual environment: `python3.8 -m venv flexmeasures-venv` or use a different tool like `mkvirtualenv` or virtualenvwrapper. You can also use
  an [Anaconda distribution](https://conda.io/docs/user-guide/tasks/manage-environments.html) as base with `conda create -n flexmeasures-venv python=3.8`.
* Activate it, e.g.: `source flexmeasures-venv/bin/activate`


## Dependencies

Install all dependencies including the ones needed for development:

    make install-for-dev

## Run locally

Now, to start the web application, you can run:

    python flexmeasures/run-local.py

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
