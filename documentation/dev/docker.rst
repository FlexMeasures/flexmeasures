.. docker:

Running via Docker
======================

FlexMeasures can be run via `docker <https://hub.docker.com/repository/docker/flexmeasures/flexmeasures>`_.

`Docker <https://docs.docker.com/get-docker/>`_ is great to save developers from installation trouble, but also for running FlexMeasures inside modern cloud environments in a scalable manner.
For now, the use case is local development. Using in production is a goal for later.

We also support running all needed parts of a FlexMeasures EMS setup via `docker-compose <https://docs.docker.com/compose/>`_, which is helpful for developers and might inform hosting efforts. 

.. warning:: The dockerization is still `under development <https://github.com/FlexMeasures/flexmeasures/projects/5>`_.


The `flexmeasures` image
-----------------------------------

Getting the image
^^^^^^^^^^^^^^^^^^^^^^^^^

You can use versions we host at Docker Hub, e.g.:

.. code-block:: bash

    docker pull flexmeasures/flexmeasures:latest


You can also build the FlexMeasures image yourself, from source:

.. code-block:: bash

    docker build -t flexmeasures/my-version . 

The tag is your choice.


Running
^^^^^^^^^^^

Running the image (as a container) might work like this (remember to get the image first, see above):

.. code-block:: bash

    docker run --env SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname --env SECRET_KEY=blabla -d --net=host flexmeasures/flexmeasures

.. note:: Don't know what your image is called (it's "tag")? We used ``flexmeasures/flexmeasures`` here, as that should be the name when pulling it from Docker Hub. You can run ``docker images`` to see which images you have.

The two minimal environment variables to run the container successfully are the database URI and the secret key.

In this example, we connect to a postgres database running on our local computer, so we use the host network. In the docker-compose section below, we use a Docker container for the database, as well.

Browsing ``http://localhost:5000`` should work now and ask you to log in.

Of course, you might not have created a user. You can use ``docker exec -it <flexmeasures-container-name> bash`` to go inside the container and use the :ref:`cli` to create everything you need. 


Configuration and customization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Using :ref:`configuration` by file is usually what you want to do. It's easier than adding environment variables to ``docker run``. Also, not all settings can be given via environment variables. A good example is the :ref:`mapbox_access_token`, so you can load maps on the dashboard.

To load a configuration file into the container when starting up, we make use of the `instance folder <https://flask.palletsprojects.com/en/2.1.x/config/#instance-folders>`_. You can put a configuration file called ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance`` and then mount that folder into the container, like this:

.. code-block:: bash

    docker run -v $(pwd)/flexmeasures-instance:/app/instance:ro -d --net=host flexmeasures/flexmeasures

.. warning:: The location of the instance folder depends on how we serve FlexMeasures. The above works with gunicorn. See the compose file for an alternative (for the FlexMeasures CLI), and you can also read the above link about the instance folder.

.. note:: This is also a way to add your custom logic (as described in :ref:`plugins`) to the container. We'll document that shortly. Plugins which should be installed (e.g. by ``pip``) are a bit more difficult to support (you'd need to add `pip install` before the actual entry point). Ideas welcome. 


The complete stack: compose
--------------------------

There are situations, for instance when developing or testing, when you want the whole stack of necessary nodes to be spun up by Docker. `Docker compose <https://docs.docker.com/compose/>`_ is the answer for that.


Build the compose stack
^^^^^^^^^^^^^^^^^

Run this:

.. code-block:: bash

    docker-compose build

This pulls the images you need, and re-builds the FlexMeasures one from code. If you change code, re-running this will re-build that image.

This compose script can also serve as an inspiration for using FlexMeasures in modern cloud environments (like Kubernetes). For instance, you might want to not build the FlexMeasures image from code, but simply pull the image from DockerHub.

.. todo:: This stack runs FlexMeasures, but misses the background worker aspect. For this, we'll add a redis node and one additional FlexMeasures node, which runs a worker as entry point instead (see `issue 418<https://github.com/FlexMeasures/flexmeasures/issues/418>`_).


Run the compose stack
^^^^^^^^^^^^^^^^^^^^^^

Start the stack like this:

.. code-block:: bash

    docker-compose up

You can see log output in the terminal, but ``docker-compose logs`` is also available to you.

Check ``docker ps`` or ``docker-compose ps`` to see if your containers are running:


.. code-block:: console

    ± docker ps
    CONTAINER ID        IMAGE                       COMMAND                  CREATED             STATUS                    PORTS                    NAMES
    6105f6d1c91f        flexmeasures_flexmeasures   "bash -c 'flexmeasur…"   45 seconds ago      Up 44 seconds (healthy)   0.0.0.0:5000->5000/tcp   flexmeasures_flexmeasures_1
    b48e4b9b113b        postgres                    "docker-entrypoint.s…"   44 hours ago        Up 45 seconds             5432/tcp                 flexmeasures_dev-db_1


The FlexMeasures container has a health check implemented, which is reflected in this output and you can see which ports are available on your machine to interact.

You can use ``docker-compose logs`` to look at output. ``docker inspect <container>`` and ``docker exec -it <container> bash`` can be quite useful to dive into details. 

.. todo:: We should provide a way to test that this is working, e.g. a list of steps. Document this, but also include that in our tsc/Release list (as a test step to see if Dockerization still works, plus a publish step for the released version).


Configuration
^^^^^^^^^^^^^^

You can pass in your own configuration (e.g. for MapBox access token, or db URI, see below) like we described above for running a container: put a file ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance``.


Data
^^^^^^

The postgres database is a test database with toy data filled in when the flexmeasures container starts.
You could also connect it to some other database, by setting a different `SQLALCHEMY_DATABASE_URI` in the config. 


Running tests
^^^^^^^^^^^^^^

You can run tests in the flexmeasures docker container, using the database service ``test-db`` in the compose file. Per default, we are using the ``dev-db`` database service.

After you've started the compose stack with ``docker-compose up``, run:

.. code-block:: console

    docker exec -it -e SQLALCHEMY_TEST_DATABASE_URI="postgresql://fm-test-db-user:fm-test-db-pass@test-db:5432/fm-test-db" <flexmeasures-container-name> pytest

This rounds up the dev experience offered by running FlexMeasures in Docker. Now you can develop FlexMeasures and also run your tests. If you develop plugins, you could extend the command being used, e.g. ``bash -c "cd /path/to/my/plugin && pytest"``. 