.. docker:

Running via Docker
======================

FlexMeasures can be run via `docker <https://docs.docker.com/>`_. TODO: link to the image once it's up.

Docker is great to save developers from installation trouble, but also for running FlexMeasures inside modern cloud environments in a scalable manner.
For now, the use case is local development. Using in production is a goal for later.

We also support running all needed parts of a FlexMeasures EMS setup via `docker-compose <https://docs.docker.com/compose/>`_, which is helpful for developers and might inform hosting efforts. 

.. warning:: The dockerization is still under development.

TODO:

- Main Dockerfile serves API (via gunicorn and a WSGI file)
- Publish one flexmeasures image per version
- Compose script defines one additional FM node, where it runs a worker as entry point instead. Document.
- Some way to test that this is working, e.g. a list of steps. Document. Also include in Release list. Could be a test step, then a publish step.


The `flexmeasures` image
-----------------------------------

Building or downloading
^^^^^^^^^^^^^^^^^^^^^^^^^

You can build the FlexMeasures image yourself:

    docker build -t flexmeasures/my-version . 

But you can also use versions we host at Docker Hub, e.g.:

    docker pull flexmeasures/flexmeasures:latest


Running
^^^^^^^^^^^

Running the image might work like this:

.. code-block:: bash

    docker run --env SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname --env SECRET_KEY=blabla -d --net=host your-image-name

The two minimal environment variables are the database URI and the secret key.
In this example, we connect to a database running on our local computer, so we use the host net.
Browsing ``http://localhost:5000`` should work.


Configuring
^^^^^^^^^^^^^

Using the :ref:`configuration` by file is sometimes easier and also not all settings can be given via environment variables.
To load a configuration file into the container when starting up, you can put a file ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance`` and then mount that folder into the container, like this:

.. code-block:: bash

    docker run --volume flexmeasures-instance/:/var/usr/flexmeasures-instance/ -d --net=host your-image-name



Build the compose stack
--------------------------

Run this:

    docker-compose build

This builds the containers you need from code. If you change code, re-running this will re-build that image.


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

You can pass in your own configuration (e.g. for MapBox access token, or db URI, see below) like we described above for running a container: Put a file ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance``.

TODO: also load plugins this way (installing them by pip will be offered later)

Data
-----

The postgres database is a test database with toy data filled in when the flexmeasures container starts.
You could also connect it to some other database, by setting a different `SQLALCHEMY_DATABASE_URI` in the config. 

