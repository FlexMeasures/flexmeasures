.. _docker-image:

Running via Docker
======================

FlexMeasures can be run via `docker <https://hub.docker.com/repository/docker/lfenergy/flexmeasures>`_.

`Docker <https://docs.docker.com/get-docker/>`_ is great to save developers from installation trouble, but also for running FlexMeasures inside modern cloud environments in a scalable manner.


.. note:: We also support running all needed parts of a FlexMeasures EMS setup via `docker-compose <https://docs.docker.com/compose/>`_, which is helpful for developers and might inform hosting efforts. See :ref:`docker-compose`. 

.. warning:: For now, the use case is local development. Using in production is a goal for later. Follow `our progress <https://github.com/FlexMeasures/flexmeasures/projects/5>`_.


The `flexmeasures` image
-----------------------------------

Getting the image
^^^^^^^^^^^^^^^^^^^^^^^^^

You can use versions we host at Docker Hub, e.g.:

.. code-block:: bash

    docker pull lfenergy/flexmeasures:latest


You can also build the FlexMeasures image yourself, from source:

.. code-block:: bash

    docker build -t flexmeasures/my-version . 

The tag is your choice.


Running
^^^^^^^^^^^

Running the image (as a container) might work like this (remember to get the image first, see above):

.. code-block:: bash

    docker run --env SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname --env SECRET_KEY=blabla  --env FLASK_ENV=development -d --net=host lfenergy/flexmeasures

.. note:: Don't know what your image is called (its "tag")? We used ``lfenergy/flexmeasures`` here, as that should be the name when pulling it from Docker Hub. You can run ``docker images`` to see which images you have.

The two minimal environment variables to run the container successfully are the database URI and the secret key, see :ref:`configuration`. ``FLASK_ENV=development`` is needed if you do not have an SSL certificate set up (the default mode is ``production``, and in that mode FlexMeasures requires https for security reasons). If you see too much output, you can also set ``LOGGING_LEVEL=INFO``.

In this example, we connect to a postgres database running on our local computer, so we use the host network. In the docker-compose section below, we use a Docker container for the database, as well.

Browsing ``http://localhost:5000`` should work now and ask you to log in.

Of course, you might not have created a user. You can use ``docker exec -it <flexmeasures-container-name> bash`` to go inside the container and use the :ref:`cli` to create everything you need. 


.. _docker_configuration:

Configuration and customization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Using :ref:`configuration` by file is usually what you want to do. It's easier than adding environment variables to ``docker run``. Also, not all settings can be given via environment variables. A good example is the :ref:`mapbox_access_token`, so you can load maps on the dashboard.

To load a configuration file into the container when starting up, we make use of the `instance folder <https://flask.palletsprojects.com/en/2.1.x/config/#instance-folders>`_. You can put a configuration file called ``flexmeasures.cfg`` into a local folder called ``flexmeasures-instance`` and then mount that folder into the container, like this:

.. code-block:: bash

    docker run -v $(pwd)/flexmeasures-instance:/app/instance:ro -d --net=host lfenergy/flexmeasures

.. warning:: The location of the instance folder depends on how we serve FlexMeasures. The above works with gunicorn. See the compose file for an alternative (for the FlexMeasures CLI), and you can also read the above link about the instance folder.

.. note:: This is also a way to add your custom logic (as described in :ref:`plugins`) to the container. We'll document that shortly. Plugins which should be installed (e.g. by ``pip``) are a bit more difficult to support (you'd need to add `pip install` before the actual entry point). Ideas welcome. 

