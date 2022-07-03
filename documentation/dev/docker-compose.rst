.. _docker-compose:

Running a complete stack with docker-compose
=============================================

To install FlexMeasures, plus the libraries and databases it depends on, on your computer is some work, and can have unexpected hurdles, e.g. depending on the operating system. A nice alternative is to let that happen within Docker. The whole stack can be run via `Docker compose <https://docs.docker.com/compose/>`_, saving the developer much time.

For this, we assume you are in the directory housing ``docker-compose.yml``.


.. note:: The minimum Docker version is 17.09 and for docker-compose we tested successfully at version 1.25. You can check your versions with ``docker[-compose] --version``.

Build the compose stack
------------------------

Run this:

.. code-block:: bash

    docker-compose build

This pulls the images you need, and re-builds the FlexMeasures one from code. If you change code, re-running this will re-build that image.

This compose script can also serve as an inspiration for using FlexMeasures in modern cloud environments (like Kubernetes). For instance, you might want to not build the FlexMeasures image from code, but simply pull the image from DockerHub.

.. todo:: This stack runs FlexMeasures, but misses the background worker aspect. For this, we'll add a redis node and one additional FlexMeasures node, which runs a worker as entry point instead (see `issue 418 <https://github.com/FlexMeasures/flexmeasures/issues/418>`_).


Run the compose stack
----------------------

Start the stack like this:

.. code-block:: bash

    docker-compose up

You can see log output in the terminal, but ``docker-compose logs`` is also available to you.

Check ``docker ps`` or ``docker-compose ps`` to see if your containers are running:


.. code-block:: console

    ± docker ps
    CONTAINER ID        IMAGE                 COMMAND                  CREATED             STATUS                    PORTS                    NAMES
    dda1a8606926        flexmeasures_server   "bash -c 'flexmeasur…"   43 seconds ago      Up 41 seconds (healthy)   0.0.0.0:5000->5000/tcp   flexmeasures_server_1
    27ed9eef1b04        postgres              "docker-entrypoint.s…"   2 days ago          Up 42 seconds             5432/tcp                 flexmeasures_dev-db_1
    90df2065e08d        postgres              "docker-entrypoint.s…"   2 days ago          Up 42 seconds             5432/tcp                 flexmeasures_test-db_1


The FlexMeasures container has a health check implemented, which is reflected in this output and you can see which ports are available on your machine to interact.

You can use ``docker-compose logs`` to look at output. ``docker inspect <container>`` and ``docker exec -it <container> bash`` can be quite useful to dive into details. 

.. todo:: We should provide a way to test that this is working, e.g. a list of steps. Document this, but also include that in our tsc/Release list (as a test step to see if Dockerization still works, plus a publish step for the released version).


Configuration
---------------

You can pass in your own configuration (e.g. for MapBox access token, or db URI, see below) like we described above for running a container: put a file ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance``.


Data
-------

The postgres database is a test database with toy data filled in when the flexmeasures container starts.
You could also connect it to some other database, by setting a different ``SQLALCHEMY_DATABASE_URI`` in the config. 


Running tests
---------------

You can run tests in the flexmeasures docker container, using the database service ``test-db`` in the compose file (per default, we are using the ``dev-db`` database service).

After you've started the compose stack with ``docker-compose up``, run:

.. code-block:: console

    docker exec -it -e SQLALCHEMY_TEST_DATABASE_URI="postgresql://fm-test-db-user:fm-test-db-pass@test-db:5432/fm-test-db" flexmeasures-server-1 pytest

This rounds up the dev experience offered by running FlexMeasures in Docker. Now you can develop FlexMeasures and also run your tests. If you develop plugins, you could extend the command being used, e.g. ``bash -c "cd /path/to/my/plugin && pytest"``. 