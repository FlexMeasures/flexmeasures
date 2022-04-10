.. docker:

Running via Docker
======================

FlexMeasures can be run via `docker <https://docs.docker.com/>`_. TODO: link to the image once it's up.

Docker is great to save developers from installation trouble, but also for running FlexMeasures inside modern cloud environments in a scalable manner.
For now, the use case is local development. Using in production is a goal for later.

We also support running all needed parts of a FlexMeasures EMS setup via `docker-compose <https://docs.docker.com/compose/>`_, which is helpful for developers and might inform hosting efforts. 

.. warning:: The dockerization is still under development.

TODO:

- Ability to load config file into container (flexmeasures.cfg, if available)
- Main Dockerfile serves API (via gunicorn and a WSGI file)
- Compose script defines one additional FM node, where it runs a worker as entry point instead. Document.
- Some way to test that this is working, e.g. a list of steps. Document. Also include in Release list. Could be a test step, then a publish step.
- Fix: flask->flexmeasures (importlib error)
- Publish one flexmeasures image per version


Download and run the default image
-----------------------------------

TODO


Build the compose stack
--------------------------

Run this:

    docker-compose build

This builds the containers you need from code. If you change code, re-running this will re-build that image.

.. note:: Of course the ``pip install`` step takes time - maybe we want to try using pip install and caching: https://medium.com/@scythargon/cache-for-python-pip-downloads-and-wheels-in-docker-67f24e7cd84e)


Run the compose stack
------------------

Start the stack like this:

    docker-compose up

You can see log output in the terminal, but ``docker-compose logs`` is also available to you.

Check ``docker ps`` or ``docker-compose ps`` to see if your containers are running and ``docker-compose logs`` to look at output. ```docker inspect <container>`` can be quite useful to dive into details. 

The FlexMeasures container has a health check implemented which is reflected in this output and you can see which ports are available on your machine to interact.


Inspect individual containers
-------------------------------

To start a bash session in the `flexmeasures` container, do this:

    docker-compose run flexmeasures bash


Configuration
----------------

You can pass in your own configuration (e.g. MapBox access token, or db URI, see below) like this: TODO


Data
-----

The postgres database is a test database with toy data filled in when the flexmeasures container starts.
You could also connect it to some other database, by setting a different `SQLALCHEMY_DATABASE_URI` in the config. 

